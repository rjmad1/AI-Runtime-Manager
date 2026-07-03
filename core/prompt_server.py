# core/prompt_server.py
# HTTP control plane and web dashboard server for AIRM.
# The HTML dashboard is loaded from core/templates/dashboard.html.

import os
import sys
import json
import time
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional

# Ensure core/ is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import manager  # noqa: E402  — thin re-export layer
import discovery  # noqa: E402
from validation import validate_provider_key_http  # noqa: E402

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


def _get_cached_discovery() -> Dict[str, Any]:
    """Return cached discovery results, refreshing after TTL expires."""
    global _discovery_cache, _discovery_cache_time
    now = time.time()
    if _discovery_cache is not None and (now - _discovery_cache_time) < _DISCOVERY_TTL_SECONDS:
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
        body = self._read_json_body()
        provider = body.get("provider", "")
        api_key = body.get("api_key", "")

        success, message = validate_provider_key_http(provider, api_key)
        if success:
            providers = manager.load_yaml(manager.PROVIDERS_PATH)
            env_var = providers.get(provider, {}).get("env_var", "")
            if env_var:
                manager.set_windows_env(env_var, api_key)
        self._send_json({"success": success, "message": message})

    def _handle_post_providers_toggle(self) -> None:
        body = self._read_json_body()
        provider = body.get("provider", "")
        enabled = body.get("enabled", False)

        providers = manager.load_yaml(manager.PROVIDERS_PATH)
        if provider in providers and isinstance(providers[provider], dict):
            providers[provider]["enabled"] = enabled
            manager.save_yaml(providers, manager.PROVIDERS_PATH)
        self._send_json({"success": True})

    def _handle_post_install(self) -> None:
        # Pre-flight check: ensure at least one API key is present OR ollama has models
        providers = manager.load_yaml(manager.PROVIDERS_PATH)
        has_keys = False
        for p_name, p_info in providers.items():
            if isinstance(p_info, dict) and p_info.get("enabled", False):
                env_var = p_info.get("env_var", "")
                if env_var and manager.get_windows_env(env_var):
                    has_keys = True
                    break

        discovery_data = _get_cached_discovery()
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
        body = self._read_json_body()
        action = body.get("action", "")
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
        if self.path == "/api/providers/validate":
            self._handle_post_providers_validate()
        elif self.path == "/api/providers/toggle":
            self._handle_post_providers_toggle()
        elif self.path == "/api/install":
            self._handle_post_install()
        elif self.path == "/api/control":
            self._handle_post_control()
        elif self.path == "/api/repair":
            from cli import cmd_repair
            cmd_repair()
            self._send_json({"success": True})
        elif self.path == "/api/backup":
            zip_path = manager.cmd_backup()
            self._send_json({"success": bool(zip_path), "path": zip_path or ""})
        elif self.path == "/api/restore":
            body = self._read_json_body()
            idx = body.get("index", 0)
            ok = manager.cmd_restore(idx)
            self._send_json({"success": ok})
        elif self.path == "/api/diagnose":
            manager.cmd_diagnose()
            self._send_json({"success": True})
        else:
            self.send_error(404)


def run_prompt_server(port: int = 8500) -> None:
    """Start the AIRM dashboard HTTP server and open the browser."""
    manager.log("INFO", f"Starting AIRM Web Dashboard on http://127.0.0.1:{port}")
    manager.log("INFO", "Press Ctrl+C to stop the dashboard server.")

    httpd = HTTPServer(("127.0.0.1", port), PromptRequestHandler)

    webbrowser.open(f"http://127.0.0.1:{port}")

    try:
        while True:
            httpd.handle_request()
    except KeyboardInterrupt:
        manager.log("INFO", "Dashboard server shut down by user.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_prompt_server()
