# core/prompt_server.py
# Lightweight Python standard library HTTP server serving the AIRM Dashboard and control panel

import os
import sys
import json
import webbrowser
import urllib.parse
import urllib.request
import urllib.error
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8500
server_running = True

# Dynamic Installation state
INSTALL_STATE = {
    "status": "idle", # idle, installing, success, failed
    "progress": 0,
    "current_task": "Waiting to start...",
    "logs": [],
    "error": None,
    "estimated_seconds_left": 0
}

# Resolve target folders
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CORE_DIR)
CONFIG_DIR = os.path.join(ROOT_DIR, "OpenClawManager")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.yaml")
PROVIDERS_PATH = os.path.join(CONFIG_DIR, "providers.yaml")

# Import manager module
try:
    import manager
    import discovery
except ImportError:
    sys.path.append(CORE_DIR)
    import manager
    import discovery

# Helper for logger integration
def add_install_log(message):
    INSTALL_STATE["logs"].append(message)
    manager.log("INFO", f"[WEB INSTALLER] {message}")

# Background Installer Worker Thread
def run_installation_worker():
    global INSTALL_STATE
    INSTALL_STATE["status"] = "installing"
    INSTALL_STATE["progress"] = 5
    INSTALL_STATE["current_task"] = "Bootstrapping system dependencies..."
    INSTALL_STATE["estimated_seconds_left"] = 45
    INSTALL_STATE["logs"] = []
    
    try:
        # Step 1: Run bootstrapper silently
        add_install_log("Executing dependency bootstrap sequence...")
        bootstrap_script = os.path.join(CORE_DIR, "bootstrap.ps1")
        
        # Invoke bootstrap script silently
        res = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", bootstrap_script],
            capture_output=True, text=True
        )
        add_install_log("System requirements check completed.")
        
        INSTALL_STATE["progress"] = 35
        INSTALL_STATE["current_task"] = "Syncing environment settings..."
        INSTALL_STATE["estimated_seconds_left"] = 30
        
        # Step 2: Configure models and compile configs
        add_install_log("Generating LiteLLM config and OpenClaw gateways...")
        manager.cmd_configure()
        add_install_log("Blueprints compiled successfully.")
        
        INSTALL_STATE["progress"] = 70
        INSTALL_STATE["current_task"] = "Launching service daemons..."
        INSTALL_STATE["estimated_seconds_left"] = 15
        
        # Step 3: Run start daemons
        add_install_log("Starting LiteLLM and OpenClaw background services...")
        manager.cmd_start()
        add_install_log("Background processes launched.")
        
        INSTALL_STATE["progress"] = 90
        INSTALL_STATE["current_task"] = "Testing system connectivity..."
        INSTALL_STATE["estimated_seconds_left"] = 5
        
        # Step 4: Run diagnostic check
        try:
            add_install_log("Executing connection diagnostic latency tests...")
            manager.cmd_diagnose()
            add_install_log("Diagnostics check complete.")
        except Exception as e:
            add_install_log(f"Warning during diagnostics check: {e}")
            
        INSTALL_STATE["progress"] = 100
        INSTALL_STATE["status"] = "success"
        INSTALL_STATE["current_task"] = "Installation and configuration complete!"
        INSTALL_STATE["estimated_seconds_left"] = 0
        add_install_log("Guided setup finalized successfully.")
        
    except Exception as e:
        INSTALL_STATE["status"] = "failed"
        INSTALL_STATE["error"] = str(e)
        INSTALL_STATE["current_task"] = "Installation failed."
        add_install_log(f"CRITICAL ERROR: {e}")

# Helper validation calls
def validate_provider_key_http(provider, api_key):
    """Perform real HTTP requests to validate API keys."""
    if not api_key or len(api_key.strip()) < 8:
        return False, "Key is too short or empty."
        
    try:
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            body = json.dumps({"contents": [{"parts": [{"text": "Say ok"}]}]}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10.0) as res:
                return True, "Key is valid."
                
        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
            body = json.dumps({
                "model": "llama-3.3-70b-specdec",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 1
            }).encode("utf-8")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0) as res:
                return True, "Key is valid."
                
        elif provider == "sambanova":
            url = "https://api.sambanova.ai/v1/chat/completions"
            body = json.dumps({
                "model": "Meta-Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 1
            }).encode("utf-8")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0) as res:
                return True, "Key is valid."
                
        elif provider == "cerebras":
            url = "https://api.cerebras.ai/v1/chat/completions"
            body = json.dumps({
                "model": "llama3.1-8b",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 1
            }).encode("utf-8")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0) as res:
                return True, "Key is valid."
                
        elif provider == "openrouter":
            url = "https://openrouter.ai/api/v1/auth/key"
            headers = {"Authorization": f"Bearer {api_key}"}
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=10.0) as res:
                return True, "Key is valid."
                
        return True, "Form check succeeded (No live endpoint test implemented)."
    except urllib.error.HTTPError as e:
        try:
            error_data = json.loads(e.read().decode())
            # Extract standard API error patterns
            if "error" in error_data and "message" in error_data["error"]:
                return False, error_data["error"]["message"]
        except Exception:
            pass
        return False, f"API rejected credential: HTTP {e.code}"
    except Exception as e:
        return False, f"Network/Connection error: {e}"

# Server Request Handler
class PromptRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute logging console spam
        pass

    def do_GET(self):
        # Serve main dashboard
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
            
        elif self.path == "/api/discovery":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = discovery.run_all_discovery(SETTINGS_PATH)
            self.wfile.write(json.dumps(data).encode("utf-8"))
            
        elif self.path == "/api/providers":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            prov_data = manager.load_yaml(PROVIDERS_PATH)
            res = {}
            for name, cfg in prov_data.items():
                env_var = cfg.get("env_var")
                key_val = manager.get_windows_env(env_var)
                res[name] = {
                    "enabled": cfg.get("enabled", False),
                    "env_var": env_var,
                    "info": cfg.get("info", ""),
                    "has_key": key_val is not None and len(key_val) > 0,
                    # Mask key output
                    "masked_key": f"{key_val[:6]}...{key_val[-4:]}" if key_val and len(key_val) > 10 else ""
                }
            self.wfile.write(json.dumps(res).encode("utf-8"))
            
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            # Retrieve active status
            status = manager.cmd_status()
            
            # Fetch last few log lines
            log_tail = []
            if os.path.exists(LOG_FILE):
                try:
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        log_tail = f.readlines()[-40:]
                except Exception:
                    pass
            
            res = {
                "services": status,
                "installer_status": INSTALL_STATE,
                "logs": [l.strip() for l in log_tail]
            }
            self.wfile.write(json.dumps(res).encode("utf-8"))
            
        elif self.path == "/api/backups":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            settings = manager.load_yaml(SETTINGS_PATH)
            backup_dir = settings.get("lifecycle", {}).get("backup_dir", "backups")
            backup_dir = os.path.abspath(os.path.join(ROOT_DIR, backup_dir))
            
            zips = []
            if os.path.exists(backup_dir):
                zips = [f for f in os.listdir(backup_dir) if f.endswith(".zip")]
            self.wfile.write(json.dumps(zips).encode("utf-8"))
            
        elif self.path == "/api/install/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(INSTALL_STATE).encode("utf-8"))
            
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body_str = self.rfile.read(content_length).decode("utf-8")
        
        try:
            body = json.loads(body_str) if body_str else {}
        except Exception:
            body = {}
            
        if self.path == "/api/providers/validate":
            provider = body.get("provider")
            key = body.get("api_key")
            
            # Run test request
            ok, msg = validate_provider_key_http(provider, key)
            
            if ok:
                # Save key persistently
                providers_data = manager.load_yaml(PROVIDERS_PATH)
                env_var = providers_data.get(provider, {}).get("env_var", f"{provider.upper()}_API_KEY")
                manager.set_windows_env(env_var, key)
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok, "message": msg}).encode("utf-8"))
            
        elif self.path == "/api/providers/toggle":
            provider = body.get("provider")
            enabled = body.get("enabled", False)
            
            providers_data = manager.load_yaml(PROVIDERS_PATH)
            if provider in providers_data:
                providers_data[provider]["enabled"] = enabled
                manager.save_yaml(providers_data, PROVIDERS_PATH)
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            
        elif self.path == "/api/control":
            action = body.get("action") # start, stop, restart
            
            if action == "start":
                manager.cmd_start()
            elif action == "stop":
                manager.cmd_stop()
            elif action == "restart":
                manager.cmd_stop()
                time.sleep(1)
                manager.cmd_start()
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            
        elif self.path == "/api/install":
            if INSTALL_STATE["status"] != "installing":
                thread = threading.Thread(target=run_installation_worker)
                thread.daemon = True
                thread.start()
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            
        elif self.path == "/api/diagnose":
            # Run diagnostics in separate thread to prevent HTTP gateway timeout
            def run_diagnose_bg():
                try:
                    manager.cmd_diagnose()
                except Exception:
                    pass
            thread = threading.Thread(target=run_diagnose_bg)
            thread.daemon = True
            thread.start()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            
        elif self.path == "/api/repair":
            manager.cmd_repair()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            
        elif self.path == "/api/backup":
            zip_path = manager.cmd_backup()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": zip_path is not None, "path": zip_path}).encode("utf-8"))
            
        elif self.path == "/api/restore":
            idx = body.get("index")
            ok = manager.cmd_restore(idx)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok}).encode("utf-8"))
            
        elif self.path == "/api/shutdown":
            # Shutdown this server
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            global server_running
            server_running = False
            
        else:
            self.send_response(404)
            self.end_headers()

def run_prompt_server():
    server_address = ("127.0.0.1", PORT)
    try:
        httpd = HTTPServer(server_address, PromptRequestHandler)
        manager.log("INFO", f"Dashboard and Control server listening on http://127.0.0.1:{PORT}")
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        
        while server_running:
            httpd.handle_request()
            
        manager.log("INFO", "Setup server shutdown cleanly.")
    except Exception as e:
        manager.log("ERROR", f"Failed to start prompt server: {e}")

# Premium HTML visual dashboard structure
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AIRM Setup & Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --sidebar-bg: #111827;
            --panel-bg: #1f2937;
            --card-bg: #111827;
            --border-color: #374151;
            --accent: #2563eb;
            --accent-glow: rgba(37, 99, 235, 0.4);
            --success: #10b981;
            --success-glow: rgba(16, 185, 129, 0.2);
            --warning: #f59e0b;
            --error: #ef4444;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            overflow: hidden;
        }

        /* Sidebar navigation */
        .sidebar {
            width: 280px;
            background-color: var(--sidebar-bg);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            padding: 2rem 1.5rem;
        }

        .brand {
            margin-bottom: 3rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .brand-logo {
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, #3b82f6, #1d4ed8);
            border-radius: 8px;
            box-shadow: 0 0 15px var(--accent-glow);
        }

        .brand-title {
            font-size: 1.25rem;
            font-weight: 700;
            background: linear-gradient(to right, #60a5fa, #3b82f6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .nav-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .nav-item {
            padding: 0.85rem 1.25rem;
            border-radius: 10px;
            cursor: pointer;
            color: var(--text-muted);
            font-weight: 500;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 0.85rem;
            border: 1px solid transparent;
        }

        .nav-item:hover {
            color: var(--text-main);
            background-color: rgba(255, 255, 255, 0.05);
        }

        .nav-item.active {
            color: var(--text-main);
            background-color: rgba(37, 99, 235, 0.15);
            border-color: rgba(37, 99, 235, 0.3);
            box-shadow: 0 0 10px rgba(37, 99, 235, 0.1);
        }

        /* Main Workspace */
        .workspace {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .top-bar {
            height: 70px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 3rem;
            background-color: rgba(17, 24, 39, 0.4);
            backdrop-filter: blur(10px);
        }

        .system-status-indicator {
            display: flex;
            align-items: center;
            gap: 1.5rem;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.85rem;
            font-weight: 600;
            padding: 0.35rem 0.85rem;
            border-radius: 9999px;
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--text-muted);
        }

        .status-dot.online {
            background-color: var(--success);
            box-shadow: 0 0 10px var(--success-glow);
        }

        .status-dot.offline {
            background-color: var(--error);
        }

        .content-panel {
            flex: 1;
            padding: 3rem;
            overflow-y: auto;
        }

        .panel-tab {
            display: none;
        }

        .panel-tab.active {
            display: block;
            animation: fadeIn 0.3s ease-in-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(5px); }
            to { opacity: 1; transform: translateY(0); }
        }

        h2.panel-title {
            font-size: 1.85rem;
            font-weight: 700;
            margin-bottom: 1.5rem;
            background: linear-gradient(to right, #ffffff, #9ca3af);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        p.panel-subtitle {
            color: var(--text-muted);
            font-size: 0.95rem;
            margin-bottom: 2.5rem;
            line-height: 1.6;
        }

        /* Dashboard and Grid Systems */
        .specs-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2.5rem;
        }

        .spec-card {
            background-color: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            position: relative;
            overflow: hidden;
            transition: border-color 0.2s;
        }

        .spec-card:hover {
            border-color: var(--accent);
        }

        .spec-label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
        }

        .spec-val {
            font-size: 1.25rem;
            font-weight: 600;
        }

        .spec-bar {
            width: 100%;
            height: 4px;
            background-color: rgba(255, 255, 255, 0.05);
            border-radius: 2px;
            margin-top: 1rem;
            overflow: hidden;
        }

        .spec-progress {
            height: 100%;
            background: linear-gradient(to right, #3b82f6, #60a5fa);
            width: 0;
            transition: width 0.5s ease-out;
        }

        .info-card {
            background-color: rgba(37, 99, 235, 0.08);
            border: 1px solid rgba(37, 99, 235, 0.2);
            padding: 1.5rem;
            border-radius: 16px;
            margin-bottom: 2.5rem;
            display: flex;
            gap: 1rem;
            align-items: center;
        }

        .info-icon {
            font-size: 2rem;
            color: #60a5fa;
        }

        /* Forms & Inputs */
        .provider-list {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        .provider-row {
            background-color: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2rem;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        .provider-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .provider-title-group {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .provider-badge {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background-color: var(--text-muted);
        }

        .provider-badge.active {
            background-color: var(--success);
            box-shadow: 0 0 10px var(--success-glow);
        }

        .provider-name {
            font-size: 1.2rem;
            font-weight: 600;
        }

        .provider-desc {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        .key-input-group {
            display: flex;
            gap: 1rem;
        }

        input[type="text"], input[type="password"] {
            flex: 1;
            padding: 0.85rem 1.25rem;
            background-color: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            color: var(--text-main);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
            transition: all 0.2s ease;
        }

        input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 8px rgba(37, 99, 235, 0.25);
        }

        .btn {
            padding: 0.85rem 1.5rem;
            border: 1px solid transparent;
            border-radius: 10px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .btn-primary {
            background-color: var(--accent);
            color: white;
        }

        .btn-primary:hover {
            background-color: #1d4ed8;
            box-shadow: 0 0 12px var(--accent-glow);
        }

        .btn-secondary {
            background-color: transparent;
            border-color: var(--border-color);
            color: var(--text-muted);
        }

        .btn-secondary:hover {
            background-color: rgba(255, 255, 255, 0.05);
            color: var(--text-main);
        }

        .btn-danger {
            background-color: var(--error);
            color: white;
        }

        .btn-danger:hover {
            background-color: #dc2626;
        }

        /* Toggle Switches */
        .switch {
            position: relative;
            display: inline-block;
            width: 46px;
            height: 24px;
        }

        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(255, 255, 255, 0.1);
            transition: .3s;
            border-radius: 24px;
            border: 1px solid var(--border-color);
        }

        .slider:before {
            position: absolute;
            content: "";
            height: 16px;
            width: 16px;
            left: 3px;
            bottom: 3px;
            background-color: var(--text-muted);
            transition: .3s;
            border-radius: 50%;
        }

        input:checked + .slider {
            background-color: var(--accent);
        }

        input:checked + .slider:before {
            transform: translateX(22px);
            background-color: white;
        }

        /* Progress Installation panel */
        .progress-box {
            background-color: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 2.5rem;
            max-width: 650px;
            margin: 0 auto;
            text-align: center;
        }

        .progress-title {
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .progress-desc {
            color: var(--text-muted);
            font-size: 0.95rem;
            margin-bottom: 2rem;
        }

        .progress-bar-container {
            width: 100%;
            height: 10px;
            background-color: rgba(255, 255, 255, 0.05);
            border-radius: 9999px;
            overflow: hidden;
            margin-bottom: 1.5rem;
        }

        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--accent), #60a5fa);
            width: 0%;
            transition: width 0.3s ease;
        }

        .progress-steps-list {
            text-align: left;
            display: flex;
            flex-direction: column;
            gap: 0.85rem;
            margin-top: 2rem;
            font-size: 0.9rem;
        }

        .progress-step-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: var(--text-muted);
        }

        .progress-step-item.active {
            color: var(--text-main);
            font-weight: 600;
        }

        .progress-step-item.completed {
            color: var(--success);
        }

        /* Console Terminal Box */
        .console-terminal {
            background-color: #030712;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
            color: #34d399;
            height: 250px;
            overflow-y: auto;
            text-align: left;
            margin-top: 2.5rem;
            box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.8);
        }

        /* Diagnostic and benchmarks layout */
        .benchmarks-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
        }

        .benchmark-card {
            background-color: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
        }

        .latency-indicator {
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent);
            margin: 0.75rem 0;
        }

        /* Custom notifications */
        .alert-box {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            padding: 1rem 1.5rem;
            border-radius: 10px;
            background-color: var(--panel-bg);
            border: 1px solid var(--border-color);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
            display: flex;
            align-items: center;
            gap: 0.75rem;
            z-index: 9999;
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .alert-box.show {
            transform: translateY(0);
            opacity: 1;
        }

        .alert-box.success {
            border-color: rgba(16, 185, 129, 0.5);
            background-color: rgba(16, 185, 129, 0.05);
        }

        .alert-box.error {
            border-color: rgba(239, 68, 68, 0.5);
            background-color: rgba(239, 68, 68, 0.05);
        }
    </style>
</head>
<body>
    <!-- Sidebar Navigation -->
    <div class="sidebar">
        <div class="brand">
            <div class="brand-logo"></div>
            <div class="brand-title">AIRM Panel</div>
        </div>
        <ul class="nav-list">
            <li class="nav-item active" onclick="switchTab('tab-welcome')">🚀 Welcome & Scan</li>
            <li class="nav-item" onclick="switchTab('tab-keys')">🔑 API Provider Keys</li>
            <li class="nav-item" onclick="switchTab('tab-ollama')">🦙 Local Ollama</li>
            <li class="nav-item" onclick="switchTab('tab-lifecycle')">⚙️ Service Manager</li>
            <li class="nav-item" onclick="switchTab('tab-benchmarks')">📊 Latency Benchmarks</li>
        </ul>
    </div>

    <!-- Main Content Workspace -->
    <div class="workspace">
        <div class="top-bar">
            <h3>Workstation Management Panel</h3>
            <div class="system-status-indicator">
                <div class="status-badge">
                    <span>LiteLLM Proxy:</span>
                    <div id="litellm-indicator" class="status-dot"></div>
                </div>
                <div class="status-badge">
                    <span>OpenClaw Gateway:</span>
                    <div id="openclaw-indicator" class="status-dot"></div>
                </div>
            </div>
        </div>

        <div class="content-panel">
            <!-- Tab 1: Welcome & Auto Discovery -->
            <div id="tab-welcome" class="panel-tab active">
                <h2 class="panel-title">System Auto-Discovery</h2>
                <p class="panel-subtitle">AIRM automatically inspects your Windows environment configuration and processes target suggestions.</p>
                
                <div class="specs-grid">
                    <div class="spec-card">
                        <div class="spec-label">Operating System</div>
                        <div id="spec-os" class="spec-val">Scanning...</div>
                    </div>
                    <div class="spec-card">
                        <div class="spec-label">CPU Controller</div>
                        <div id="spec-cpu" class="spec-val">Scanning...</div>
                    </div>
                    <div class="spec-card">
                        <div class="spec-label">GPU Display Card</div>
                        <div id="spec-gpu" class="spec-val">Scanning...</div>
                    </div>
                    <div class="spec-card">
                        <div class="spec-label">Dedicated VRAM</div>
                        <div id="spec-vram" class="spec-val">Scanning...</div>
                    </div>
                    <div class="spec-card">
                        <div class="spec-label">System RAM (GB)</div>
                        <div id="spec-ram" class="spec-val">Scanning...</div>
                    </div>
                    <div class="spec-card">
                        <div class="spec-label">Storage (C: Drive)</div>
                        <div id="spec-disk" class="spec-val">Scanning...</div>
                    </div>
                </div>

                <div class="info-card">
                    <div class="info-icon">💡</div>
                    <div>
                        <h4 style="margin-bottom: 0.25rem;">Smart Recommendations & Capability Mapping</h4>
                        <p id="system-rec" class="spec-desc" style="color: var(--text-muted); font-size: 0.9rem;">Analysing hardware configurations...</p>
                    </div>
                </div>

                <div class="progress-box" id="guided-installer-box" style="display:none;">
                    <div class="progress-title" id="inst-title">Guided Setup Deployment</div>
                    <div class="progress-desc" id="inst-desc">Deploy and launch the complete stack with zero terminal input.</div>
                    
                    <div class="progress-bar-container">
                        <div id="inst-progress-bar" class="progress-bar-fill"></div>
                    </div>
                    
                    <div style="display:flex; justify-content:space-between; font-size: 0.85rem; color: var(--text-muted)">
                        <span id="inst-task">Idle</span>
                        <span id="inst-time">Remaining: --</span>
                    </div>

                    <button class="btn btn-primary" id="btn-start-install" onclick="startGuidedInstall()" style="margin: 1.5rem auto 0 auto;">
                        Launch Auto Installation
                    </button>
                </div>
            </div>

            <!-- Tab 2: API Keys Configuration -->
            <div id="tab-keys" class="panel-tab">
                <h2 class="panel-title">AI Provider Credentials Catalog</h2>
                <p class="panel-subtitle">Manage cloud AI provider configuration keys. API keys are validated immediately and saved securely in Windows environment variables.</p>
                
                <div class="provider-list" id="providers-container">
                    <!-- Dynamic rendering -->
                </div>
            </div>

            <!-- Tab 3: Local Ollama Models -->
            <div id="tab-ollama" class="panel-tab">
                <h2 class="panel-title">Local Model Integration (Ollama)</h2>
                <p class="panel-subtitle">AIRM detects installed GGUF models on Ollama, verifies hardware suitability limits, and connects them to LiteLLM automatically.</p>
                
                <div class="specs-grid" id="ollama-specs-grid" style="margin-bottom: 2rem;">
                    <div class="spec-card">
                        <div class="spec-label">Ollama Service Status</div>
                        <div id="ollama-status-text" class="spec-val">Loading...</div>
                    </div>
                    <div class="spec-card">
                        <div class="spec-label">Local Model Count</div>
                        <div id="ollama-model-count" class="spec-val">0</div>
                    </div>
                </div>

                <div id="ollama-models-container" class="provider-list">
                    <!-- Dynamic model listings -->
                </div>
            </div>

            <!-- Tab 4: Lifecycle Service Manager -->
            <div id="tab-lifecycle" class="panel-tab">
                <h2 class="panel-title">AIRM Operations Center</h2>
                <p class="panel-subtitle">Start and stop services, run backups, trigger self-healing, and monitor live log tail outputs.</p>
                
                <div class="specs-grid">
                    <div class="spec-card" style="display:flex; flex-direction:column; gap:1.5rem; justify-content:center;">
                        <div class="spec-label">Global Controls</div>
                        <div style="display:flex; gap:1rem;">
                            <button class="btn btn-primary" onclick="controlServices('start')">▶ Start stack</button>
                            <button class="btn btn-danger" onclick="controlServices('stop')">■ Stop stack</button>
                            <button class="btn btn-secondary" onclick="controlServices('restart')">↺ Restart</button>
                        </div>
                    </div>
                    <div class="spec-card" style="display:flex; flex-direction:column; gap:1.5rem; justify-content:center;">
                        <div class="spec-label">System Utilities</div>
                        <div style="display:flex; gap:1rem;">
                            <button class="btn btn-secondary" onclick="runSelfHealing()">🔧 Run Self-Healing</button>
                            <button class="btn btn-secondary" onclick="createBackup()">💾 Backup Settings</button>
                        </div>
                    </div>
                </div>

                <div style="margin-top: 2rem;">
                    <h3 style="margin-bottom: 1rem;">Active Backups</h3>
                    <div id="backups-container" style="display:flex; flex-direction:column; gap:0.5rem;">
                        <!-- List backups -->
                    </div>
                </div>

                <div class="console-terminal" id="installer-terminal">
                    <!-- Logs stream -->
                </div>
            </div>

            <!-- Tab 5: Benchmarks -->
            <div id="tab-benchmarks" class="panel-tab">
                <h2 class="panel-title">Latency Connectivity Benchmarks</h2>
                <p class="panel-subtitle">Benchmark configured local and cloud model endpoints by sending minimal token requests to calculate performance.</p>
                
                <button class="btn btn-primary" onclick="triggerBenchmarks()" style="margin-bottom: 2.5rem;">
                    🚀 Execute Benchmarks Test
                </button>

                <div class="benchmarks-grid" id="benchmarks-container">
                    <!-- Dynamic rendering -->
                </div>
            </div>
        </div>
    </div>

    <!-- Alert Dialog -->
    <div id="alert-box" class="alert-box">
        <span id="alert-text">Notification message</span>
    </div>

    <!-- JavaScript logic -->
    <script>
        let currentTab = 'tab-welcome';
        
        function switchTab(tabId) {
            document.querySelectorAll('.panel-tab').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            
            document.getElementById(tabId).classList.add('active');
            
            // Find nav item index
            const tabs = ['tab-welcome', 'tab-keys', 'tab-ollama', 'tab-lifecycle', 'tab-benchmarks'];
            const idx = tabs.indexOf(tabId);
            document.querySelectorAll('.sidebar .nav-item')[idx].classList.add('active');
            
            currentTab = tabId;
        }

        // Display messages
        function notify(msg, type='success') {
            const box = document.getElementById('alert-box');
            const txt = document.getElementById('alert-text');
            box.className = 'alert-box show ' + type;
            txt.textContent = msg;
            setTimeout(() => { box.classList.remove('show'); }, 3000);
        }

        // Fetch System Specs
        async function fetchSpecs() {
            try {
                const res = await fetch('/api/discovery');
                const data = await res.json();
                
                document.getElementById('spec-os').textContent = data.specs.os || 'N/A';
                document.getElementById('spec-cpu').textContent = data.specs.cpu || 'N/A';
                document.getElementById('spec-gpu').textContent = data.specs.gpus.map(g => g.name).join(' / ') || 'None';
                document.getElementById('spec-vram').textContent = data.specs.gpus.map(g => g.vram_gb + ' GB').join(' / ') || 'N/A';
                document.getElementById('spec-ram').textContent = data.specs.ram_gb + ' GB';
                document.getElementById('spec-disk').textContent = data.specs.disk.free_gb + ' GB Free / ' + data.specs.disk.total_gb + ' GB';
                
                document.getElementById('system-rec').textContent = data.recommendations.recommendation;
                
                // Show installation trigger block if tools are present
                if (data.tools.python) {
                    document.getElementById('guided-installer-box').style.display = 'block';
                }
                
                // Render Ollama info
                document.getElementById('ollama-status-text').textContent = data.ollama.online ? (data.ollama.api_connected ? 'Online (API Connected)' : 'Stopped (Serve Needed)') : 'Not Installed';
                document.getElementById('ollama-model-count').textContent = data.ollama.models.length;
                
                renderOllamaModels(data.ollama.models);
            } catch(e) {
                console.error(e);
            }
        }

        function renderOllamaModels(models) {
            const container = document.getElementById('ollama-models-container');
            if (models.length === 0) {
                container.innerHTML = `<div class="spec-card">No local models found on Ollama. Run 'ollama pull llama3' in your terminal.</div>`;
                return;
            }
            
            container.innerHTML = models.map(m => {
                let badgeClass = 'badge-missing';
                if (m.status === 'excellent') badgeClass = 'badge-found';
                if (m.status === 'partial') badgeClass = 'badge-found';
                return `
                    <div class="provider-row">
                        <div class="provider-header">
                            <div>
                                <h3 class="provider-name">${m.name}</h3>
                                <span class="provider-desc">Parameter Count: ${m.parameter_size} | Size: ${Math.round(m.size_bytes/(1024**2))}MB | Required Memory: ${m.required_ram_gb}GB</span>
                            </div>
                            <span class="status-badge" style="border-color:${m.status==='excellent'?'#10b981':'#f59e0b'}">${m.suitability}</span>
                        </div>
                        <p style="font-size:0.9rem; color:var(--text-muted)">${m.comment}</p>
                    </div>
                `;
            }).join('');
        }

        // Fetch Providers credentials
        async function fetchProviders() {
            try {
                const res = await fetch('/api/providers');
                const data = await res.json();
                const container = document.getElementById('providers-container');
                
                container.innerHTML = Object.entries(data).map(([name, info]) => {
                    return `
                        <div class="provider-row">
                            <div class="provider-header">
                                <div class="provider-title-group">
                                    <div class="provider-badge ${info.enabled ? 'active' : ''}"></div>
                                    <span class="provider-name">${name.toUpperCase()}</span>
                                </div>
                                <div style="display:flex; align-items:center; gap:1rem;">
                                    <span style="font-size:0.85rem; color:var(--text-muted)">Enable Provider</span>
                                    <label class="switch">
                                        <input type="checkbox" ${info.enabled ? 'checked' : ''} onchange="toggleProvider('${name}', this.checked)">
                                        <span class="slider"></span>
                                    </label>
                                </div>
                            </div>
                            <p class="provider-desc">${info.info}</p>
                            
                            <div class="key-input-group" id="key-group-${name}">
                                <input type="password" id="input-${name}" placeholder="${info.has_key ? '●●●●●●●●●● (Configured)' : 'Enter API Key...'}" />
                                <button class="btn btn-primary" onclick="validateKey('${name}')">Save & Validate</button>
                            </div>
                            <div id="feedback-${name}" style="font-size: 0.85rem; display:none; margin-top: 0.25rem;"></div>
                        </div>
                    `;
                }).join('');
            } catch(e) {
                console.error(e);
            }
        }

        async function toggleProvider(provider, enabled) {
            try {
                const res = await fetch('/api/providers/toggle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({provider, enabled})
                });
                const d = await res.json();
                if (d.success) {
                    notify(`${provider.toUpperCase()} state updated successfully.`);
                    fetchProviders();
                }
            } catch(e) {
                notify('Failed to toggle provider.', 'error');
            }
        }

        async function validateKey(provider) {
            const val = document.getElementById('input-' + provider).value.strip ? document.getElementById('input-' + provider).value.trim() : document.getElementById('input-' + provider).value;
            const feedback = document.getElementById('feedback-' + provider);
            
            if (!val) {
                notify('Please enter a key.', 'error');
                return;
            }
            
            feedback.style.display = 'block';
            feedback.style.color = 'var(--text-muted)';
            feedback.textContent = 'Testing credential endpoint validation...';
            
            try {
                const res = await fetch('/api/providers/validate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({provider, api_key: val})
                });
                const d = await res.json();
                
                if (d.success) {
                    feedback.style.color = 'var(--success)';
                    feedback.textContent = '✓ Validation Success: ' + d.message;
                    notify(`${provider.toUpperCase()} credentials validated and saved!`);
                    fetchProviders();
                } else {
                    feedback.style.color = 'var(--error)';
                    feedback.textContent = '✗ Validation Error: ' + d.message;
                    notify('Credential validation failed.', 'error');
                }
            } catch(e) {
                feedback.style.color = 'var(--error)';
                feedback.textContent = '✗ Network error: ' + e;
            }
        }

        // Guided Installer progress Polling
        let installInterval = null;
        async function startGuidedInstall() {
            try {
                const res = await fetch('/api/install', {method: 'POST'});
                const data = await res.json();
                if (data.success) {
                    notify('Background installation process launched.');
                    document.getElementById('btn-start-install').disabled = true;
                    installInterval = setInterval(pollInstallProgress, 1000);
                }
            } catch(e) {
                notify('Failed to trigger installation.', 'error');
            }
        }

        async function pollInstallProgress() {
            try {
                const res = await fetch('/api/install/status');
                const data = await res.json();
                
                const fill = document.getElementById('inst-progress-bar');
                const title = document.getElementById('inst-title');
                const desc = document.getElementById('inst-desc');
                const task = document.getElementById('inst-task');
                const timer = document.getElementById('inst-time');
                
                fill.style.width = data.progress + '%';
                task.textContent = 'Current task: ' + data.current_task;
                timer.textContent = 'Remaining: ~' + data.estimated_seconds_left + 's';
                
                if (data.status === 'installing') {
                    title.textContent = 'Guided Setup In Progress (' + data.progress + '%)';
                } else if (data.status === 'success') {
                    title.textContent = 'Installation Complete!';
                    desc.textContent = 'AIRM stack deployed. Access the control endpoints dashboard.';
                    notify('AIRM fully configured and running.');
                    clearInterval(installInterval);
                    document.getElementById('btn-start-install').disabled = false;
                } else if (data.status === 'failed') {
                    title.textContent = 'Installation Failed';
                    desc.textContent = 'Error: ' + data.error;
                    notify('Setup failed: ' + data.error, 'error');
                    clearInterval(installInterval);
                    document.getElementById('btn-start-install').disabled = false;
                }
            } catch(e) {
                clearInterval(installInterval);
            }
        }

        // Service Daemon Management Panel
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                // Indicators
                const l_dot = document.getElementById('litellm-indicator');
                const c_dot = document.getElementById('openclaw-indicator');
                
                l_dot.className = 'status-dot ' + (data.services.litellm.status === 'ONLINE' ? 'online' : 'offline');
                c_dot.className = 'status-dot ' + (data.services.openclaw.status === 'ONLINE' ? 'online' : 'offline');
                
                // Logs Console
                const consoleBox = document.getElementById('installer-terminal');
                consoleBox.innerHTML = data.logs.map(l => {
                    let color = '#f3f4f6';
                    if (l.includes('[ERROR]')) color = 'var(--error)';
                    if (l.includes('[WARNING]')) color = 'var(--warning)';
                    if (l.includes('[SUCCESS]')) color = 'var(--success)';
                    return `<div style="color:${color}">${l}</div>`;
                }).join('');
                consoleBox.scrollTop = consoleBox.scrollHeight;
            } catch(e) {
                console.error(e);
            }
        }

        async function controlServices(action) {
            try {
                notify(`Requesting service ${action}...`);
                const res = await fetch('/api/control', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action})
                });
                const d = await res.json();
                if (d.success) {
                    notify(`Services command '${action}' completed.`);
                    fetchStatus();
                }
            } catch(e) {
                notify('Command execution error.', 'error');
            }
        }

        async function runSelfHealing() {
            try {
                notify('Executing self-repair diagnostics...');
                const res = await fetch('/api/repair', {method: 'POST'});
                const data = await res.json();
                if (data.success) {
                    notify('Self-healing checklist completed.');
                    fetchStatus();
                }
            } catch(e) {
                notify('Self-repair trigger error.', 'error');
            }
        }

        async function createBackup() {
            try {
                notify('Creating configuration backup zip...');
                const res = await fetch('/api/backup', {method: 'POST'});
                const data = await res.json();
                if (data.success) {
                    notify('Backup archive created successfully.');
                    fetchBackups();
                }
            } catch(e) {
                notify('Failed to generate backup.', 'error');
            }
        }

        async function fetchBackups() {
            try {
                const res = await fetch('/api/backups');
                const zips = await res.json();
                const container = document.getElementById('backups-container');
                if (zips.length === 0) {
                    container.innerHTML = '<span style="color:var(--text-muted)">No backups created yet.</span>';
                    return;
                }
                container.innerHTML = zips.map((zip, idx) => `
                    <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.02); padding:0.75rem 1rem; border-radius:8px; border:1px solid var(--border-color)">
                        <span>${zip}</span>
                        <button class="btn btn-secondary" style="padding:0.4rem 0.8rem; font-size:0.8rem;" onclick="restoreBackup(${idx})">Restore</button>
                    </div>
                `).join('');
            } catch(e) {
                console.error(e);
            }
        }

        async function restoreBackup(idx) {
            try {
                notify('Restoring configuration from backup index...');
                const res = await fetch('/api/restore', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({index: idx})
                });
                const d = await res.json();
                if (d.success) {
                    notify('Configurations successfully restored!');
                    fetchSpecs();
                    fetchProviders();
                } else {
                    notify('Restore transaction failed.', 'error');
                }
            } catch(e) {
                notify('Restore call error.', 'error');
            }
        }

        // Diagnostics benchmarks
        async function triggerBenchmarks() {
            try {
                notify('Triggering diagnostic endpoint latency benchmarks...');
                await fetch('/api/diagnose', {method: 'POST'});
                notify('Benchmark tests initiated in background. Generating latency dashboard...');
            } catch(e) {
                notify('Failed to launch diagnostics.', 'error');
            }
        }

        async function pollDiagnostics() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                // Read from logs if diagnostics results were compiled recently or make a call to fetch them
                // For simplicity, fetch the HTML report compiled at generated/health-report.html if possible or print list
            } catch(e) {}
        }

        // Page Load Routine
        window.onload = function() {
            fetchSpecs();
            fetchProviders();
            fetchStatus();
            fetchBackups();
            
            // Continuous state poll loop
            setInterval(fetchStatus, 3000);
        };
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    run_prompt_server()
