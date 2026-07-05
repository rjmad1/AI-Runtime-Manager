# core/prompt_server.py
# HTTP control plane and web dashboard server for AIRM.
# The HTML dashboard is loaded from core/templates/dashboard.html.

import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

from . import (
    auth,
    discovery,
    manager,  # thin re-export layer
)
from .config import _validate_provider_name
from .diagnostics import LiteLLMOfflineError
from .validation import validate_provider_key_http

# ── Thread-safe installation progress state ──
_install_lock = threading.Lock()
INSTALL_STATE: Dict[str, Any] = {
    "status": "idle",
    "progress": 0,
    "current_task": "Waiting...",
    "estimated_seconds_left": 0,
    "error": "",
    "logs": [],
}

# ── Discovery cache with TTL ──
_discovery_cache: Optional[Dict[str, Any]] = None
_discovery_cache_time: float = 0
_DISCOVERY_TTL_SECONDS: int = 30

# ── Authentication Token ──
# Session-scoped anti-CSRF token: generated fresh on every server start,
# handed to the browser via the URL fragment, required on state-changing POSTs.
_AUTH_TOKEN: Optional[str] = None
_AUTH_TOKEN_LOCK = threading.Lock()

def _get_auth_token() -> str:
    """Get or generate the session authentication token."""
    global _AUTH_TOKEN
    with _AUTH_TOKEN_LOCK:
        if _AUTH_TOKEN is None:
            _AUTH_TOKEN = secrets.token_hex(24)
        return _AUTH_TOKEN

def _validate_auth_token(token: str) -> bool:
    """Validate authentication token."""
    if not token:
        return False
    return secrets.compare_digest(token, _get_auth_token())


def _get_cached_discovery(force: bool = False) -> Dict[str, Any]:
    """Return cached discovery results, refreshing after TTL expires."""
    global _discovery_cache, _discovery_cache_time
    now = time.time()
    if not force and _discovery_cache is not None and (now - _discovery_cache_time) < _DISCOVERY_TTL_SECONDS:
        return _discovery_cache
    _discovery_cache = discovery.run_all_discovery(manager.SETTINGS_PATH)
    _discovery_cache_time = now
    return _discovery_cache


# ── Dependency inventory cache (probes spawn subprocesses; longer TTL) ──
_inventory_cache: Optional[Dict[str, Any]] = None
_inventory_cache_time: float = 0
_INVENTORY_TTL_SECONDS: int = 300


def _get_cached_inventory() -> Dict[str, Any]:
    """Return cached dependency inventory, refreshing after TTL expires."""
    global _inventory_cache, _inventory_cache_time
    now = time.time()
    if _inventory_cache is not None and (now - _inventory_cache_time) < _INVENTORY_TTL_SECONDS:
        return _inventory_cache
    _inventory_cache = discovery.discover_dependency_inventory()
    _inventory_cache_time = now
    return _inventory_cache


# ── Constants ──
ROOT_DIR: str = manager.ROOT_DIR
LOGS_DIR: str = manager.LOGS_DIR
LOG_FILE: str = manager.LOG_FILE

# ── Load HTML dashboard template once at import time ──
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
_DASHBOARD_PATH = os.path.join(_TEMPLATE_DIR, "dashboard.html")

try:
    with open(_DASHBOARD_PATH, "r", encoding="utf-8") as _f:
        HTML_DASHBOARD = _f.read()
except FileNotFoundError:
    HTML_DASHBOARD = "<html><body><h1>Dashboard template not found</h1><p>Expected at: {}</p></body></html>".format(
        _DASHBOARD_PATH
    )


def _update_install_state(**kwargs: Any) -> None:
    """Thread-safe update of INSTALL_STATE."""
    with _install_lock:
        INSTALL_STATE.update(kwargs)


def add_install_log(msg: str) -> None:
    """Append a log message to the installation progress state."""
    with _install_lock:
        INSTALL_STATE["logs"].append(msg)


def run_installation_worker() -> None:
    """Background thread that runs the full guided installation pipeline."""
    try:
        _update_install_state(status="installing", progress=5, current_task="Compiling configurations...")
        add_install_log("[INFO] Compiling LiteLLM and OpenClaw configurations...")

        manager.cmd_configure()
        _update_install_state(progress=40, current_task="Starting daemon services...", estimated_seconds_left=30)
        add_install_log("[SUCCESS] Configuration blueprints compiled.")

        add_install_log("[INFO] Starting LiteLLM and OpenClaw background services...")
        manager.cmd_start()
        _update_install_state(progress=90, current_task="Verifying health...", estimated_seconds_left=5)
        add_install_log("[SUCCESS] Daemon services initialized.")

        _update_install_state(status="success", progress=100, current_task="Complete", estimated_seconds_left=0)
        add_install_log("[SUCCESS] AIRM guided setup completed successfully.")
    except Exception as e:
        _update_install_state(status="failed", error=str(e))
        add_install_log(f"[ERROR] Installation failed: {e}")


class PromptRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the AIRM dashboard and REST API."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP access logging."""
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_content: str) -> None:
        """Send an HTML response."""
        body = html_content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _identity(self) -> Optional[Dict[str, Any]]:
        """Resolve the request credential into an identity, or None.

        Accepted credentials: the per-session dashboard token (full admin,
        legacy behavior), an AIRM API key, or a JWT issued by /api/auth/login."""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        if _validate_auth_token(token):
            return {"subject": "dashboard-session", "role": "admin",
                    "perms": auth.ROLES["admin"], "type": "session"}
        return auth.authenticate(token)

    def _check_auth(self) -> bool:
        """Check authentication token in headers."""
        return self._identity() is not None

    def _require_auth(self, permission: str = "") -> bool:
        """Require authentication (401) and, if given, a permission (403)."""
        identity = self._identity()
        if identity is None:
            self._send_json({"error": "Unauthorized", "message": "Authentication required"}, 401)
            return False
        if permission and not auth.authorize(identity, permission):
            self._send_json({"error": "Forbidden",
                             "message": f"Requires '{permission}' permission "
                                        f"(role: {identity['role']})"}, 403)
            return False
        return True

    def _drain_body(self) -> None:
        """Read the full request body up front. Responding (e.g. 401) while
        unread bytes sit in the socket makes some platforms send RST instead
        of delivering the response — every POST must drain before replying."""
        length = int(self.headers.get("Content-Length", 0))
        self._raw_body = self.rfile.read(length) if length else b""

    def _read_json_body(self) -> Dict[str, Any]:
        """Parse the JSON request body captured by _drain_body."""
        raw = getattr(self, "_raw_body", b"")
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _handle_get_discovery(self) -> None:
        data = _get_cached_discovery()
        self._send_json(data)

    def _handle_get_providers(self) -> None:
        providers = manager.load_yaml(manager.PROVIDERS_PATH)
        result: Dict[str, Any] = {}
        for name, info in providers.items():
            if isinstance(info, dict):
                env_var = info.get("env_var", "")
                has_key = bool(manager.get_windows_env(env_var)) if env_var else False
                result[name] = {
                    "enabled": info.get("enabled", False),
                    "env_var": env_var,
                    "info": info.get("info", ""),
                    "has_key": has_key,
                }
        self._send_json(result)

    def _handle_get_status(self) -> None:
        status_data = manager.cmd_status()
        logs: List[str] = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    logs = f.readlines()[-50:]
                    logs = [line.strip() for line in logs]
            except Exception:
                pass
        self._send_json({"services": status_data, "logs": logs})

    def _handle_get_backups(self) -> None:
        settings = manager.load_yaml(manager.SETTINGS_PATH)
        backup_dir = settings.get("lifecycle", {}).get("backup_dir", "backups")
        backup_dir = os.path.abspath(os.path.join(ROOT_DIR, backup_dir))
        zips: List[str] = []
        if os.path.exists(backup_dir):
            zips = [f for f in os.listdir(backup_dir) if f.endswith(".zip")]
        self._send_json(zips)

    def _handle_get_watchdog_logs(self) -> None:
        """Expose real-time self-healing logs."""
        logs: List[str] = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    # Filter logs related to self-healing, repair, and watchdog, or return last 200
                    all_lines = f.readlines()
                    watchdog_lines = [line.strip() for line in all_lines if any(kw in line.lower() for kw in ("watchdog", "repair", "self-healing", "restart", "fail"))]
                    logs = watchdog_lines[-200:]
            except Exception:
                pass
        self._send_json({"logs": logs})

    def _handle_get_install_status(self) -> None:
        with _install_lock:
            self._send_json(dict(INSTALL_STATE))

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET requests."""
        if self.path == "/":
            self._send_html(HTML_DASHBOARD)
            return

        handlers = {
            "/api/discovery": self._handle_get_discovery,
            "/api/inventory": lambda: self._send_json(_get_cached_inventory()),
            "/api/providers": self._handle_get_providers,
            "/api/status": self._handle_get_status,
            "/api/install/status": self._handle_get_install_status,
            "/api/backups": self._handle_get_backups,
            "/api/logs/watchdog": self._handle_get_watchdog_logs,
        }

        if self.path in handlers:
            if self._require_auth("read"):
                handlers[self.path]()
        else:
            self.send_error(404)

    def _handle_post_login(self) -> None:
        """Exchange username/password for a JWT (12h). No prior auth required."""
        body = self._read_json_body()
        username = str(body.get("username", ""))[:100]
        password = str(body.get("password", ""))
        role = auth.verify_password(username, password)
        if role is None:
            time.sleep(0.5)  # blunt brute-force throttle on the loopback plane
            self._send_json({"success": False, "message": "Invalid credentials"}, 401)
            return
        token = auth.jwt_issue(username, role)
        self._send_json({"success": True, "token": token, "role": role,
                         "expires_in": auth.JWT_TTL_SECONDS})

    def _handle_post_providers_validate(self) -> None:
        if not self._require_auth("configure"):
            return
        body = self._read_json_body()
        provider = body.get("provider", "")
        api_key = body.get("api_key", "")

        # Validate provider name to prevent injection
        if not _validate_provider_name(provider):
            self._send_json({"success": False, "message": "Invalid provider name"}, 400)
            return

        success, message = validate_provider_key_http(provider, api_key)
        if success:
            providers = manager.load_yaml(manager.PROVIDERS_PATH)
            env_var = providers.get(provider, {}).get("env_var", "")
            if env_var:
                manager.set_windows_env(env_var, api_key)
        self._send_json({"success": success, "message": message})

    def _handle_post_providers_toggle(self) -> None:
        if not self._require_auth("configure"):
            return
        body = self._read_json_body()
        provider = body.get("provider", "")
        enabled = body.get("enabled", False)

        # Validate provider name
        if not _validate_provider_name(provider):
            self._send_json({"success": False, "message": "Invalid provider name"}, 400)
            return

        providers = manager.load_yaml(manager.PROVIDERS_PATH)
        if provider in providers and isinstance(providers[provider], dict):
            providers[provider]["enabled"] = enabled
            manager.save_yaml(providers, manager.PROVIDERS_PATH)
        self._send_json({"success": True})

    def _handle_post_install(self) -> None:
        if not self._require_auth("configure"):
            return
        # Pre-flight check: ensure at least one API key is present OR ollama has models
        providers = manager.load_yaml(manager.PROVIDERS_PATH)
        has_keys = False
        for p_name, p_info in providers.items():
            if isinstance(p_info, dict) and p_info.get("enabled", False):
                env_var = p_info.get("env_var", "")
                if env_var and manager.get_windows_env(env_var):
                    has_keys = True
                    break

        discovery_data = _get_cached_discovery(force=True)
        ollama_models = discovery_data.get("ollama", {}).get("models", [])

        if not has_keys and not ollama_models:
            self._send_json({"success": False, "message": "Missing API credentials. Please configure at least one provider API key or install Ollama models before continuing."})
            return

        with _install_lock:
            if INSTALL_STATE["status"] == "installing":
                self._send_json({"success": False, "message": "Installation already in progress."})
                return
            INSTALL_STATE.update({
                "status": "installing", "progress": 0,
                "current_task": "Initializing...", "estimated_seconds_left": 60,
                "error": "", "logs": [],
            })
        t = threading.Thread(target=run_installation_worker, daemon=True)
        t.start()
        self._send_json({"success": True})

    def _handle_post_control(self) -> None:
        if not self._require_auth("control"):
            return
        body = self._read_json_body()
        action = body.get("action", "")

        # Validate action
        if action not in ["start", "stop", "restart"]:
            self._send_json({"success": False, "message": "Invalid action"}, 400)
            return

        if action == "start":
            manager.cmd_start()
        elif action == "stop":
            manager.cmd_stop()
        elif action == "restart":
            manager.cmd_stop()
            manager.cmd_start()
        self._send_json({"success": True})

    def _handle_post_repair(self) -> None:
        from .cli import cmd_repair
        # interactive=False: never blocks on console consent from a server
        # thread — dependency installs are planned and reported instead.
        cmd_repair(interactive=False)
        self._send_json({"success": True})

    def _handle_post_backup(self) -> None:
        zip_path = manager.cmd_backup()
        self._send_json({"success": bool(zip_path), "path": zip_path or ""})

    def _handle_post_restore(self) -> None:
        body = self._read_json_body()
        idx = body.get("index", 0)
        ok = manager.cmd_restore(idx)
        self._send_json({"success": ok})

    def _handle_post_diagnose(self) -> None:
        try:
            manager.cmd_diagnose()
        except LiteLLMOfflineError as e:
            self._send_json({"success": False, "message": str(e)})
            return
        self._send_json({"success": True})

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST requests."""
        self._drain_body()
        
        # Public or self-authenticating routes
        if self.path == "/api/auth/check":
            if self._require_auth():
                self._send_json({"success": True})
            return
            
        public_handlers = {
            "/api/auth/login": self._handle_post_login,
            "/api/providers/validate": self._handle_post_providers_validate,
            "/api/providers/toggle": self._handle_post_providers_toggle,
            "/api/install": self._handle_post_install,
            "/api/control": self._handle_post_control,
        }
        
        if self.path in public_handlers:
            public_handlers[self.path]()
            return

        # Control routes requiring auth
        control_handlers = {
            "/api/repair": self._handle_post_repair,
            "/api/backup": self._handle_post_backup,
            "/api/restore": self._handle_post_restore,
            "/api/diagnose": self._handle_post_diagnose,
        }

        if self.path in control_handlers:
            if self._require_auth("control"):
                control_handlers[self.path]()
        else:
            self.send_error(404)


def run_prompt_server(port: int = 8500) -> None:
    """Start the AIRM dashboard HTTP server and open the browser."""
    manager.ensure_runtime_dirs()

    from . import migrations
    try:
        migrations.ensure_current()
    except migrations.MigrationError as e:
        manager.log("ERROR", str(e))
        return
    token = _get_auth_token()
    
    httpd = None
    for attempt_port in range(port, port + 10):
        try:
            httpd = HTTPServer(("127.0.0.1", attempt_port), PromptRequestHandler)
            port = attempt_port
            break
        except OSError:
            continue
            
    if httpd is None:
        manager.log("ERROR", f"Could not find an open port for the web dashboard (tried {port}-{port+9}).")
        return

    manager.log("INFO", f"Starting AIRM Web Dashboard on http://127.0.0.1:{port}")
    manager.log("INFO", f"Dashboard Auth Token: {token}")
    manager.log("INFO", "Copy the token above into the dashboard login prompt.")
    manager.log("INFO", "Press Ctrl+C to stop the dashboard server.")

    # Token rides in the URL fragment: never sent over the network, read once
    # by the dashboard JS for automatic login, then stripped from the URL.
    webbrowser.open(f"http://127.0.0.1:{port}/#token={token}")

    try:
        while True:
            httpd.handle_request()
    except KeyboardInterrupt:
        manager.log("INFO", "Dashboard server shut down by user.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_prompt_server()
