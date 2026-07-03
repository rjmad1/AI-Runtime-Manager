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

    def _check_auth(self) -> bool:
        """Check authentication token in headers."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            return _validate_auth_token(token)
        return False

    def _require_auth(self) -> bool:
        """Require authentication, send 401 if missing."""
        if not self._check_auth():
            self._send_json({"error": "Unauthorized", "message": "Authentication required"}, 401)
            return False
        return True

    def _read_json_body(self) -> Dict[str, Any]:
        """Read and parse JSON from the request body."""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
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

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET requests."""
        if self.path == "/":
            self._send_html(HTML_DASHBOARD)
        elif self.path == "/api/discovery":
            self._handle_get_discovery()
        elif self.path == "/api/providers":
            self._handle_get_providers()
        elif self.path == "/api/status":
            self._handle_get_status()
        elif self.path == "/api/install/status":
            with _install_lock:
                self._send_json(dict(INSTALL_STATE))
        elif self.path == "/api/backups":
            self._handle_get_backups()
        else:
            self.send_error(404)

    def _handle_post_providers_validate(self) -> None:
        if not self._require_auth():
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
        if not self._require_auth():
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
        if not self._require_auth():
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
        if not self._require_auth():
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

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST requests."""
        if self.path == "/api/auth/check":
            if self._require_auth():
                self._send_json({"success": True})
        elif self.path == "/api/providers/validate":
            self._handle_post_providers_validate()
        elif self.path == "/api/providers/toggle":
            self._handle_post_providers_toggle()
        elif self.path == "/api/install":
            self._handle_post_install()
        elif self.path == "/api/control":
            self._handle_post_control()
        elif self.path == "/api/repair":
            if not self._require_auth():
                return
            from .cli import cmd_repair
            cmd_repair()
            self._send_json({"success": True})
        elif self.path == "/api/backup":
            if not self._require_auth():
                return
            zip_path = manager.cmd_backup()
            self._send_json({"success": bool(zip_path), "path": zip_path or ""})
        elif self.path == "/api/restore":
            if not self._require_auth():
                return
            body = self._read_json_body()
            idx = body.get("index", 0)
            ok = manager.cmd_restore(idx)
            self._send_json({"success": ok})
        elif self.path == "/api/diagnose":
            if not self._require_auth():
                return
            try:
                manager.cmd_diagnose()
            except LiteLLMOfflineError as e:
                self._send_json({"success": False, "message": str(e)})
                return
            self._send_json({"success": True})
        else:
            self.send_error(404)


def run_prompt_server(port: int = 8500) -> None:
    """Start the AIRM dashboard HTTP server and open the browser."""
    manager.ensure_runtime_dirs()
    token = _get_auth_token()
    manager.log("INFO", f"Starting AIRM Web Dashboard on http://127.0.0.1:{port}")
    manager.log("INFO", f"Dashboard Auth Token: {token}")
    manager.log("INFO", "Copy the token above into the dashboard login prompt.")
    manager.log("INFO", "Press Ctrl+C to stop the dashboard server.")

    httpd = HTTPServer(("127.0.0.1", port), PromptRequestHandler)

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
