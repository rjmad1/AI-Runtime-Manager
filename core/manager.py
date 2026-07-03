# core/manager.py
# Unified Lifecycle Management Daemon for AIRM (OpenClaw Workstation)

import os
import sys
import json
import re
import time
import shutil
import zipfile
import platform
import argparse
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

# Import local discovery engine
try:
    import discovery
except ImportError:
    # Handle path routing if run from root directory
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import discovery

# --- Constants & Paths ---
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CORE_DIR)
CONFIG_DIR = os.path.join(ROOT_DIR, "OpenClawManager")
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")

SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.yaml")
PROVIDERS_PATH = os.path.join(CONFIG_DIR, "providers.yaml")
MODELS_PATH = os.path.join(CONFIG_DIR, "models.yaml")

LITELLM_CONFIG_PATH = os.path.join(GENERATED_DIR, "config.yaml")
OPENCLAW_CONFIG_PATH = os.path.join(GENERATED_DIR, "openclaw.json")
SERVICES_STATE_PATH = os.path.join(GENERATED_DIR, "services.json")

# Ensure folders exist
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Logger setup
LOG_FILE = os.path.join(LOGS_DIR, "installer.log")

def log(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_msg = message
    # Secrets masking (mask API keys like sk-... or nvapi-...)
    clean_msg = re.sub(r'(sk-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+', r'\1...', clean_msg)
    clean_msg = re.sub(r'(nvapi-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+', r'\1...', clean_msg)
    
    color = ""
    reset = "\033[0m"
    if level == "INFO":
        color = "\033[36m" # Cyan
    elif level == "SUCCESS":
        color = "\033[32m" # Green
    elif level == "WARNING":
        color = "\033[33m" # Yellow
    elif level == "ERROR":
        color = "\033[31m" # Red
        
    print(f"{color}[{level}] {clean_msg}{reset}")
    sys.stdout.flush()
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{level}] {clean_msg}\n")
    except Exception:
        pass

# Safe YAML Loader
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

def load_yaml(path):
    if not os.path.exists(path):
        return {}
    if HAS_YAML:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            log("WARNING", f"Failed to parse YAML file {path}: {e}. Falling back to default schema.")
            return {}
    else:
        # Fallback YAML parser for basic fields
        data = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if v.lower() == "true":
                        v = True
                    elif v.lower() == "false":
                        v = False
                    elif v.isdigit():
                        v = int(v)
                    data[k] = v
        return data

def save_yaml(data, path):
    if HAS_YAML:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    else:
        with open(path, "w", encoding="utf-8") as f:
            for k, v in data.items():
                if isinstance(v, dict):
                    f.write(f"{k}:\n")
                    for subk, subv in v.items():
                        f.write(f"  {subk}: {json.dumps(subv)}\n")
                else:
                    f.write(f"{k}: {json.dumps(v)}\n")

# --- Process State & Registry Functions ---

def load_services_state():
    if os.path.exists(SERVICES_STATE_PATH):
        try:
            with open(SERVICES_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"litellm": None, "openclaw": None}

def save_services_state(state):
    try:
        with open(SERVICES_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log("ERROR", f"Failed to save services state: {e}")

def get_pids_on_port(port):
    pids = set()
    try:
        res = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=True)
        pattern = re.compile(rf":{port}\s+\S+\s+LISTENING\s+(\d+)")
        for line in res.stdout.splitlines():
            m = pattern.search(line)
            if m:
                pids.add(int(m.group(1)))
    except Exception as e:
        log("WARNING", f"Could not list TCP connections: {e}")
    return list(pids)

def is_pid_running(pid):
    if not pid:
        return False
    try:
        res = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in res.stdout
    except Exception:
        return False

def kill_process_tree(pid):
    try:
        if not is_pid_running(pid):
            return True
        log("INFO", f"Terminating PID {pid} and its children gracefully...")
        subprocess.run(["taskkill", "/T", "/PID", str(pid)], capture_output=True)
        
        # Wait up to 3 seconds for exit
        for _ in range(3):
            time.sleep(1)
            if not is_pid_running(pid):
                return True
                
        # Force kill fallback
        log("WARNING", f"PID {pid} still alive. Force killing...")
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        return True
    except Exception as e:
        log("WARNING", f"Could not stop process PID {pid}: {e}")
        return False

def scavenge_ports(ports):
    for port in ports:
        pids = get_pids_on_port(port)
        if pids:
            log("WARNING", f"Port {port} occupied by PIDs {pids}. Cleaning up...")
            for pid in pids:
                kill_process_tree(pid)
        else:
            log("INFO", f"Port {port} is clear.")

# --- Windows persistent user variable helpers ---

def get_windows_env(name):
    try:
        cmd = f"[System.Environment]::GetEnvironmentVariable('{name}', 'User')"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, check=True)
        val = res.stdout.strip()
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(name)

def set_windows_env(name, value):
    try:
        cmd = f"[System.Environment]::SetEnvironmentVariable('{name}', '{value}', 'User')"
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, check=True)
        os.environ[name] = value
        return True
    except Exception as e:
        log("ERROR", f"Failed to save env variable {name}: {e}")
        return False

# --- Core CLI Lifecycle Commands ---

def cmd_install():
    log("INFO", "Starting guided visual setup assistant...")
    # Migrate old keys
    gemini_key = get_windows_env("GEMINI_API_KEY")
    if not gemini_key:
        google_key = get_windows_env("GOOGLE_API_KEY")
        if google_key:
            log("INFO", "Migrating GOOGLE_API_KEY to GEMINI_API_KEY...")
            set_windows_env("GEMINI_API_KEY", google_key)

    # Launch prompt_server.py
    try:
        server_script = os.path.join(CORE_DIR, "prompt_server.py")
        log("INFO", f"Opening Web Control Center. Running server script: {server_script}")
        # Run prompt_server.py (non-blocking if called from bootstrapper, but standard install runs it in foreground)
        subprocess.run([sys.executable, server_script])
    except Exception as e:
        log("ERROR", f"Failed to launch installation assistant: {e}")

def cmd_configure():
    log("INFO", "Compiling configuration blueprints...")
    
    settings = load_yaml(SETTINGS_PATH)
    providers = load_yaml(PROVIDERS_PATH)
    models_reg = load_yaml(MODELS_PATH)
    
    if not settings or not providers or not models_reg:
        log("ERROR", "YAML settings files are missing or corrupted. Run 'Repair.bat' to restore them.")
        sys.exit(1)
        
    # Get system and tools status
    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]
    
    # 1. Fetch Ollama local models if running
    ollama_enabled = settings.get("ollama", {}).get("enabled", True)
    ollama_api = settings.get("ollama", {}).get("api_base", "http://127.0.0.1:11434")
    ollama_autostart = settings.get("ollama", {}).get("autostart", True)
    
    ollama_models = []
    if ollama_enabled:
        ollama_models = discovery.get_ollama_models(ollama_api)
        if not ollama_models and ollama_autostart and "ollama" in tools:
            # Auto-start Ollama
            log("INFO", "Starting Ollama service...")
            try:
                subprocess.Popen([tools["ollama"], "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(5):
                    time.sleep(1)
                    ollama_models = discovery.get_ollama_models(ollama_api)
                    if ollama_models:
                        log("SUCCESS", "Ollama connected successfully.")
                        break
            except Exception as e:
                log("WARNING", f"Could not serve Ollama: {e}")
                
    # 2. Compile LiteLLM config
    litellm_models = []
    active_model_ids = set()
    
    # Cloud models from models.yaml
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        if p_cfg.get("enabled", False):
            env_var = p_cfg.get("env_var")
            key_val = get_windows_env(env_var)
            if key_val:
                model_entry = {
                    "model_name": m.get("id"),
                    "litellm_params": {
                        "model": m.get("litellm_model"),
                        "api_key": f"os.environ/{env_var}"
                    }
                }
                litellm_models.append(model_entry)
                active_model_ids.add(m.get("id"))
                
    # Ollama models dynamically
    for om in ollama_models:
        om_name = om.get("name")
        ollama_id = f"ollama/{om_name}"
        model_entry = {
            "model_name": ollama_id,
            "litellm_params": {
                "model": ollama_id,
                "api_base": ollama_api
            }
        }
        litellm_models.append(model_entry)
        active_model_ids.add(ollama_id)
        
    # Set fallbacks
    active_fallbacks = {}
    for m in models_reg.get("models", []):
        mid = m.get("id")
        if mid in active_model_ids and m.get("fallbacks"):
            fbs = [fb for fb in m.get("fallbacks") if fb in active_model_ids]
            if fbs:
                active_fallbacks[mid] = fbs
                
    # Create final LiteLLM dict
    litellm_config = {
        "model_list": litellm_models,
        "litellm_settings": {
            "drop_params": settings.get("litellm", {}).get("drop_params", True),
            "set_verbose": settings.get("litellm", {}).get("set_verbose", False)
        },
        "router_settings": {
            "routing_strategy": settings.get("litellm", {}).get("routing_strategy", "latency-based-routing"),
            "num_retries": settings.get("litellm", {}).get("num_retries", 3),
            "request_timeout": settings.get("litellm", {}).get("request_timeout", 30),
            "fallbacks": [{k: v} for k, v in active_fallbacks.items()]
        }
    }
    
    save_yaml(litellm_config, LITELLM_CONFIG_PATH)
    log("SUCCESS", f"LiteLLM config compiled: {LITELLM_CONFIG_PATH}")
    
    # 3. Compile OpenClaw openclaw.json
    openclaw_models = []
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        if p_cfg.get("enabled", False) and get_windows_env(p_cfg.get("env_var")):
            openclaw_models.append({
                "id": m.get("id"),
                "name": m.get("name"),
                "contextWindow": m.get("context_window", 4096),
                "maxTokens": m.get("max_tokens", 4096)
            })
            
    for om in ollama_models:
        om_name = om.get("name")
        openclaw_models.append({
            "id": f"ollama/{om_name}",
            "name": f"{om_name} (Ollama)",
            "contextWindow": 4096,
            "maxTokens": 4096
        })
        
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_cfg = {
        "models": {
            "providers": {
                "litellm": {
                    "baseUrl": f"http://localhost:{litellm_port}",
                    "apiKey": "${LITELLM_API_KEY}",
                    "api": "openai-completions",
                    "models": openclaw_models
                }
            }
        }
    }
    
    with open(OPENCLAW_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(openclaw_cfg, f, indent=2)
    log("SUCCESS", f"OpenClaw gateway config compiled: {OPENCLAW_CONFIG_PATH}")
    
    # 4. Merge into active ~/.openclaw/openclaw.json configuration safely
    config_dir = settings.get("openclaw", {}).get("config_dir")
    if not config_dir:
        config_dir = os.path.join(os.path.expanduser("~"), ".openclaw")
    os.makedirs(config_dir, exist_ok=True)
    
    active_claw_path = os.path.join(config_dir, "openclaw.json")
    existing_data = {}
    
    if os.path.exists(active_claw_path):
        # Backup first
        backup_path = active_claw_path + ".bak"
        shutil.copy2(active_claw_path, backup_path)
        try:
            with open(active_claw_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception as e:
            log("WARNING", f"Corrupted active config: {e}. Re-initializing.")
            
    # Add dynamic gateway secure token
    import secrets
    if "gateway" not in existing_data:
        existing_data["gateway"] = {
            "auth": {"mode": "token", "token": secrets.token_hex(24)},
            "bind": "loopback",
            "mode": "local",
            "port": settings.get("openclaw", {}).get("port", 18789)
        }
    else:
        # Prevent insecure static defaults
        auth = existing_data["gateway"].get("auth", {})
        if auth.get("token") == "7d07bed5a8d8621d4dab6bec133d7297e58f915902437007":
            log("WARNING", "Upgrading default static token to dynamic secure token...")
            if "auth" not in existing_data["gateway"]:
                existing_data["gateway"]["auth"] = {}
            existing_data["gateway"]["auth"]["token"] = secrets.token_hex(24)
            
    # Update litellm provider and models defaults
    if "models" not in existing_data:
        existing_data["models"] = {}
    if "providers" not in existing_data["models"]:
        existing_data["models"]["providers"] = {}
        
    existing_data["models"]["providers"]["litellm"] = openclaw_cfg["models"]["providers"]["litellm"]
    
    # Configure agents defaults
    if "agents" not in existing_data:
        existing_data["agents"] = {}
    if "defaults" not in existing_data["agents"]:
        existing_data["agents"]["defaults"] = {}
        
    primary = "litellm/gemini-2.5-flash"
    fallbacks = []
    active_ids = [m["id"] for m in openclaw_models]
    if active_ids:
        primary = f"litellm/{active_ids[0]}"
        fallbacks = [f"litellm/{aid}" for aid in active_ids[1:]]
        
    existing_data["agents"]["defaults"]["model"] = {
        "primary": primary,
        "fallbacks": fallbacks
    }
    
    agent_models = {}
    for aid in active_ids:
        agent_models[f"litellm/{aid}"] = {}
    existing_data["agents"]["defaults"]["models"] = agent_models
    
    if "workspace" not in existing_data["agents"]["defaults"]:
        existing_data["agents"]["defaults"]["workspace"] = os.path.join(config_dir, "workspace")
        
    # Write back
    try:
        with open(active_claw_path, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2)
        log("SUCCESS", f"Successfully synced active configuration: {active_claw_path}")
    except Exception as e:
        log("ERROR", f"Failed to sync openclaw.json: {e}")
        if os.path.exists(active_claw_path + ".bak"):
            shutil.copy2(active_claw_path + ".bak", active_claw_path)
            log("INFO", "Rolled back configuration from backup.")

def cmd_start():
    log("INFO", "Starting AIRM system stack daemons...")
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    litellm_key = settings.get("litellm", {}).get("api_key", "sk-litellm-key")
    
    # Clean rogue ports first
    if settings.get("lifecycle", {}).get("auto_cleanup_ports", True):
        scavenge_ports([litellm_port, openclaw_port])
        
    # Compile configs
    cmd_configure()
    
    # Setup process env
    os.environ["LITELLM_API_KEY"] = litellm_key
    os.environ["OPENCLAW_GATEWAY_PORT"] = str(openclaw_port)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    
    providers = load_yaml(PROVIDERS_PATH)
    for p_name, p_info in providers.items():
        if p_info.get("enabled", False):
            var = p_info.get("env_var")
            val = get_windows_env(var)
            if val:
                os.environ[var] = val
                
    # 1. Spawn LiteLLM Proxy
    log("INFO", f"Spawning LiteLLM Proxy on port {litellm_port}...")
    venv_litellm = os.path.join(ROOT_DIR, ".venv", "Scripts", "litellm.exe")
    if os.path.exists(venv_litellm):
        litellm_args = [venv_litellm, "--config", LITELLM_CONFIG_PATH, "--port", str(litellm_port)]
    else:
        python_exe = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = "python"
        litellm_args = [python_exe, "-m", "litellm", "--config", LITELLM_CONFIG_PATH, "--port", str(litellm_port)]
        
    litellm_log = open(os.path.join(LOGS_DIR, "litellm.log"), "w", encoding="utf-8")
    
    try:
        # Spawn detached on Windows (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB)
        litellm_flags = 0x00000008 | 0x00000200 | 0x01000000 if platform.system() == "Windows" else 0
        litellm_proc = subprocess.Popen(
            litellm_args,
            stdout=litellm_log,
            stderr=litellm_log,
            creationflags=litellm_flags,
            close_fds=True
        )
    except Exception as e:
        log("ERROR", f"Failed to spawn LiteLLM daemon: {e}")
        sys.exit(1)
        
    # Poll LiteLLM health
    log("INFO", "Polling LiteLLM Proxy readiness...")
    ready = False
    for _ in range(30):
        try:
            req = urllib.request.Request(f"http://localhost:{litellm_port}/health/readiness")
            with urllib.request.urlopen(req, timeout=1.0) as res:
                if "healthy" in res.read().decode().lower():
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if ready:
        log("SUCCESS", "LiteLLM Proxy is online.")
    else:
        log("WARNING", "LiteLLM Proxy is taking longer than expected to launch.")
        
    # 2. Spawn OpenClaw Gateway
    log("INFO", f"Spawning OpenClaw Gateway on port {openclaw_port}...")
    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    node_exe = sys_details["tools"].get("node", "node.exe")
    
    local_dist = os.path.join(ROOT_DIR, "node_modules", "openclaw", "dist", "index.js")
    global_appdata_dist = os.path.join(os.environ.get("AppData", ""), "npm", "node_modules", "openclaw", "dist", "index.js")
    
    openclaw_args = []
    if os.path.exists(local_dist):
        openclaw_exe = node_exe
        openclaw_args = [local_dist, "gateway", "--port", str(openclaw_port)]
    elif os.path.exists(global_appdata_dist):
        openclaw_exe = node_exe
        openclaw_args = [global_appdata_dist, "gateway", "--port", str(openclaw_port)]
    else:
        openclaw_exe = "cmd.exe"
        openclaw_args = ["/c", "openclaw", "gateway", "--port", str(openclaw_port)]
        
    openclaw_log = open(os.path.join(LOGS_DIR, "openclaw.log"), "w", encoding="utf-8")
    
    try:
        openclaw_flags = 0x00000008 | 0x00000200 | 0x01000000 if platform.system() == "Windows" else 0
        openclaw_proc = subprocess.Popen(
            [openclaw_exe] + openclaw_args,
            stdout=openclaw_log,
            stderr=openclaw_log,
            creationflags=openclaw_flags,
            close_fds=True
        )
    except Exception as e:
        log("ERROR", f"Failed to spawn OpenClaw daemon: {e}")
        kill_process_tree(litellm_proc.pid)
        sys.exit(1)
        
    # Save active PIDs
    save_services_state({
        "litellm": litellm_proc.pid,
        "openclaw": openclaw_proc.pid
    })
    
    log("SUCCESS", f"Daemons initialized. PIDs: LiteLLM={litellm_proc.pid}, OpenClaw={openclaw_proc.pid}")

def cmd_stop():
    log("INFO", "Terminating active daemon processes...")
    state = load_services_state()
    
    if state.get("litellm"):
        kill_process_tree(state["litellm"])
    if state.get("openclaw"):
        kill_process_tree(state["openclaw"])
        
    # Double check ports
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    scavenge_ports([litellm_port, openclaw_port])
    
    # Reset registry
    save_services_state({"litellm": None, "openclaw": None})
    log("SUCCESS", "All services stopped.")

def cmd_status():
    log("INFO", "Inspecting runtime state...")
    state = load_services_state()
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    
    l_pid = state.get("litellm")
    c_pid = state.get("openclaw")
    
    l_alive = is_pid_running(l_pid) if l_pid else False
    c_alive = is_pid_running(c_pid) if c_pid else False
    
    # Cross check ports
    l_pids_on_port = get_pids_on_port(litellm_port)
    c_pids_on_port = get_pids_on_port(openclaw_port)
    
    l_status = "ONLINE" if (l_alive or l_pids_on_port) else "OFFLINE"
    c_status = "ONLINE" if (c_alive or c_pids_on_port) else "OFFLINE"
    
    print("\n==============================================")
    print("      AIRM Server Daemon Status Dashboard")
    print("==============================================")
    print(f"LiteLLM Proxy (Port {litellm_port}):     {l_status} (PID: {l_pid or 'N/A'}, Active on Port: {l_pids_on_port})")
    print(f"OpenClaw Gateway (Port {openclaw_port}):  {c_status} (PID: {c_pid or 'N/A'}, Active on Port: {c_pids_on_port})")
    print("==============================================")
    
    return {
        "litellm": {"status": l_status, "pid": l_pid, "pids_on_port": l_pids_on_port},
        "openclaw": {"status": c_status, "pid": c_pid, "pids_on_port": c_pids_on_port}
    }

def cmd_diagnose():
    log("INFO", "Running endpoint connectivity and speed benchmarks...")
    
    settings = load_yaml(SETTINGS_PATH)
    providers = load_yaml(PROVIDERS_PATH)
    models_reg = load_yaml(MODELS_PATH)
    
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    litellm_key = settings.get("litellm", {}).get("api_key", "sk-litellm-key")
    
    # 1. Dependency discovery
    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]
    specs = sys_details["specs"]
    
    diagnostics = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "os": specs["os"],
        "gpu": " / ".join([g["name"] for g in specs["gpus"]]) if specs["gpus"] else "CPU Only",
        "tools": tools,
        "models": []
    }
    
    # 2. Check LiteLLM status
    l_pids = get_pids_on_port(litellm_port)
    if not l_pids:
        log("ERROR", f"LiteLLM Proxy is OFFLINE on port {litellm_port}. Cannot execute diagnostics.")
        sys.exit(1)
        
    # 3. Model benchmarking
    active_models = []
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        if p_cfg.get("enabled", False) and get_windows_env(p_cfg.get("env_var")):
            active_models.append(m)
            
    # Add Ollama local models
    ollama_api = settings.get("ollama", {}).get("api_base", "http://127.0.0.1:11434")
    ollama_models = discovery.get_ollama_models(ollama_api)
    for om in ollama_models:
        om_name = om.get("name")
        active_models.append({
            "id": f"ollama/{om_name}",
            "name": f"{om_name} (Ollama)",
            "provider": "ollama"
        })
        
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {litellm_key}"
    }
    
    for am in active_models:
        model_id = am.get("id")
        friendly_name = am.get("name")
        provider = am.get("provider")
        
        log("INFO", f"Benchmarking latency for {friendly_name} ({model_id})...")
        
        body = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Respond with only one word: test"}],
            "max_tokens": 3
        }
        
        start = time.perf_counter()
        success = False
        latency = 0
        error_msg = ""
        response_text = ""
        
        try:
            req = urllib.request.Request(
                f"http://localhost:{litellm_port}/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12.0) as res:
                latency = int((time.perf_counter() - start) * 1000)
                res_data = json.loads(res.read().decode())
                response_text = res_data['choices'][0]['message']['content'].strip()
                success = True
                log("SUCCESS", f"  Response returned in {latency}ms: '{response_text}'")
        except urllib.error.HTTPError as e:
            latency = int((time.perf_counter() - start) * 1000)
            try:
                error_msg = json.loads(e.read().decode())['error']['message']
            except Exception:
                error_msg = str(e)
            log("ERROR", f"  Request failed: {error_msg}")
        except Exception as e:
            latency = int((time.perf_counter() - start) * 1000)
            error_msg = str(e)
            log("ERROR", f"  Request failed: {error_msg}")
            
        diagnostics["models"].append({
            "id": model_id,
            "name": friendly_name,
            "provider": provider,
            "success": success,
            "latency_ms": latency if success else None,
            "response": response_text,
            "error": error_msg
        })
        
    generate_diagnostic_reports(diagnostics)
    return diagnostics

def generate_diagnostic_reports(diagnostics):
    md_path = os.path.join(GENERATED_DIR, "health-report.md")
    html_path = os.path.join(GENERATED_DIR, "health-report.html")
    
    # 1. MD Report
    md = [
        "# AIRM Diagnostics & Connectivity Report",
        f"\n**Execution Timestamp:** {diagnostics['timestamp']}",
        f"**Operating System:** {diagnostics['os']}",
        f"**Video Controller:** {diagnostics['gpu']}\n",
        "## Dependency Audit",
        "| Package | Registry Status | Target Filepath |",
        "| :--- | :--- | :--- |"
    ]
    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        status = "FOUND" if tool in diagnostics["tools"] else "MISSING"
        path = diagnostics["tools"].get(tool, "N/A")
        md.append(f"| {tool.upper()} | {status} | `{path}` |")
        
    md.append("\n## Endpoint Latency registry")
    md.append("| Provider / Model ID | Status | Latency (ms) | Output Summary / Error |")
    md.append("| :--- | :--- | :--- | :--- |")
    
    for m in diagnostics["models"]:
        status = "HEALTHY" if m["success"] else "FAILED"
        latency = f"{m['latency_ms']} ms" if m["success"] else "N/A"
        desc = f"Returned: '{m['response']}'" if m["success"] else f"Error: {m['error']}"
        md.append(f"| {m['name']} (`{m['id']}`) | {status} | {latency} | {desc} |")
        
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
        
    # 2. Beautiful HTML Report
    html = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "  <meta charset='UTF-8'>",
        "  <title>AIRM Diagnostics Console</title>",
        "  <link href='https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap' rel='stylesheet'>",
        "  <style>",
        "    :root { --bg: #0f172a; --card: #1e293b; --border: #334155; --accent: #3b82f6; --success: #10b981; --error: #ef4444; --text: #f8fafc; --muted: #94a3b8; }",
        "    * { box-sizing: border-box; margin: 0; padding: 0; }",
        "    body { font-family: 'Outfit', sans-serif; background-color: var(--bg); color: var(--text); padding: 3rem 1.5rem; line-height: 1.6; }",
        "    .container { max-width: 1000px; margin: 0 auto; }",
        "    header { margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; }",
        "    h1 { font-size: 2.25rem; font-weight: 700; background: linear-gradient(to right, #60a5fa, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }",
        "    .meta-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; margin-bottom: 2.5rem; }",
        "    .meta-card { background: var(--card); border: 1px solid var(--border); padding: 1.25rem; border-radius: 12px; }",
        "    .meta-label { font-size: 0.85rem; color: var(--muted); text-transform: uppercase; margin-bottom: 0.25rem; }",
        "    .meta-value { font-size: 1.15rem; font-weight: 600; }",
        "    table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-bottom: 2.5rem; }",
        "    th, td { padding: 1rem 1.25rem; text-align: left; }",
        "    th { background: #1e293b; font-weight: 600; border-bottom: 1px solid var(--border); }",
        "    tr:not(:last-child) { border-bottom: 1px solid var(--border); }",
        "    .badge { display: inline-block; padding: 0.2rem 0.6rem; font-size: 0.75rem; font-weight: 600; border-radius: 9999px; text-transform: uppercase; }",
        "    .badge-found { background: rgba(16, 185, 129, 0.15); color: var(--success); }",
        "    .badge-missing { background: rgba(239, 68, 68, 0.15); color: var(--error); }",
        "    .model-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }",
        "    .model-card { background: var(--card); border: 1px solid var(--border); padding: 1.5rem; border-radius: 16px; transition: transform 0.2s; }",
        "    .model-card:hover { transform: translateY(-2px); border-color: var(--accent); }",
        "    .model-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }",
        "    .model-name { font-size: 1.2rem; font-weight: 600; }",
        "    .model-id { font-size: 0.8rem; color: var(--muted); font-family: monospace; }",
        "    .latency { font-size: 1.5rem; font-weight: 700; color: var(--accent); margin: 0.5rem 0; }",
        "    .error-box { background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); color: #fca5a5; padding: 0.75rem; border-radius: 8px; font-size: 0.8rem; font-family: monospace; word-break: break-all; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <div class='container'>",
        "    <header>",
        "      <h1>AIRM Integrity Diagnostics Report</h1>",
        "      <p style='color: var(--muted); margin-top: 0.25rem;'>Workstation Endpoint Benchmarks</p>",
        "    </header>",
        "    <div class='meta-grid'>",
        f"      <div class='meta-card'><div class='meta-label'>Timestamp</div><div class='meta-value'>{diagnostics['timestamp']}</div></div>",
        f"      <div class='meta-card'><div class='meta-label'>OS Details</div><div class='meta-value'>{diagnostics['os']}</div></div>",
        f"      <div class='meta-card'><div class='meta-label'>Video Controllers</div><div class='meta-value'>{diagnostics['gpu']}</div></div>",
        "    </div>",
        "    <h2>Prerequisite Software Checks</h2>",
        "    <table>",
        "      <thead><tr><th>Dependency</th><th>Availability</th><th>Filepath</th></tr></thead>",
        "      <tbody>"
    ]
    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        status = "FOUND" if tool in diagnostics["tools"] else "MISSING"
        badge = "badge-found" if tool in diagnostics["tools"] else "badge-missing"
        path = diagnostics["tools"].get(tool, "N/A")
        html.append(f"        <tr><td><strong>{tool.upper()}</strong></td><td><span class='badge {badge}'>{status}</span></td><td><code>{path}</code></td></tr>")
        
    html.extend([
        "      </tbody>",
        "    </table>",
        "    <h2>Provider Latency Benchmarks</h2>",
        "    <div class='model-grid'>"
    ])
    for m in diagnostics["models"]:
        badge = "badge-found" if m["success"] else "badge-missing"
        status_txt = "Healthy" if m["success"] else "Failed"
        latency_txt = f"{m['latency_ms']} ms" if m["success"] else "Offline"
        
        html.append(f"      <div class='model-card'><div class='model-header'><div><div class='model-name'>{m['name']}</div><div class='model-id'>{m['id']}</div></div><span class='badge {badge}'>{status_txt}</span></div><div class='latency'>{latency_txt}</div>")
        if m["success"]:
            html.append(f"        <div style='font-size: 0.85rem; color: var(--muted)'>Response: <span style='color: var(--text); font-style: italic'>\"{m['response']}\"</span></div>")
        else:
            html.append(f"        <div class='error-box'>{m['error']}</div>")
        html.append("      </div>")
        
    html.extend([
        "    </div>",
        "  </div>",
        "</body>",
        "</html>"
    ])
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    log("SUCCESS", f"Diagnostic health reports generated: health-report.md and health-report.html")

def cmd_repair():
    log("INFO", "Initiating system self-healing check...")
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    
    # 1. Re-scavenge occupied ports
    log("INFO", "Port Auditing: release lock on workstation ports...")
    scavenge_ports([litellm_port, openclaw_port])
    
    # 2. Check and regenerate configuration files
    log("INFO", "Configuration Auditing: checking configuration blueprint schemas...")
    
    # If settings/providers/models.yaml are missing or empty, recreate templates
    if not os.path.exists(SETTINGS_PATH) or os.path.getsize(SETTINGS_PATH) == 0:
        log("WARNING", "settings.yaml was corrupted or missing. Restoring default template...")
        default_settings = {
            "litellm": {"host": "127.0.0.1", "port": 4000, "api_key": "sk-litellm-key", "set_verbose": False, "drop_params": True, "routing_strategy": "latency-based-routing", "num_retries": 3, "request_timeout": 30},
            "openclaw": {"host": "127.0.0.1", "port": 18789, "config_dir": ""},
            "ollama": {"enabled": True, "api_base": "http://127.0.0.1:11434", "autostart": True},
            "lifecycle": {"log_level": "INFO", "backup_dir": "backups", "auto_cleanup_ports": True}
        }
        save_yaml(default_settings, SETTINGS_PATH)
        
    if not os.path.exists(PROVIDERS_PATH) or os.path.getsize(PROVIDERS_PATH) == 0:
        log("WARNING", "providers.yaml was corrupted or missing. Restoring default template...")
        default_providers = {
            "gemini": {"enabled": True, "env_var": "GEMINI_API_KEY", "info": "Free tier available at Google AI Studio"},
            "groq": {"enabled": True, "env_var": "GROQ_API_KEY", "info": "Free tier available at Groq Console"},
            "sambanova": {"enabled": True, "env_var": "SAMBANOVA_API_KEY", "info": "Free API key available at SambaNova Cloud"},
            "cerebras": {"enabled": True, "env_var": "CEREBRAS_API_KEY", "info": "Free API key available at Cerebras Console"},
            "openrouter": {"enabled": True, "env_var": "OPENROUTER_API_KEY", "info": "Sign up at OpenRouter"}
        }
        save_yaml(default_providers, PROVIDERS_PATH)
        
    if not os.path.exists(MODELS_PATH) or os.path.getsize(MODELS_PATH) == 0:
        log("WARNING", "models.yaml was corrupted or missing. Restoring default template...")
        default_models = {"models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "gemini", "litellm_model": "gemini/gemini-2.5-flash", "context_window": 1048576, "max_tokens": 8192, "fallbacks": ["llama-3.3-70b-sambanova", "llama-3.3-70b-groq"]},
            {"id": "llama-3.3-70b-groq", "name": "Llama 3.3 70B (Groq)", "provider": "groq", "litellm_model": "groq/llama-3.3-70b-versatile", "context_window": 4096, "max_tokens": 4096, "fallbacks": ["llama-3.3-70b-sambanova", "llama-3.1-70b-cerebras"]},
            {"id": "llama-3.3-70b-sambanova", "name": "Llama 3.3 70B (SambaNova)", "provider": "sambanova", "litellm_model": "sambanova/Meta-Llama-3.3-70B-Instruct", "context_window": 4096, "max_tokens": 4096, "fallbacks": ["llama-3.3-70b-groq", "llama-3.1-70b-cerebras"]},
            {"id": "llama-3.1-70b-cerebras", "name": "Llama 3.1 70B (Cerebras)", "provider": "cerebras", "litellm_model": "cerebras/llama3.1-70b", "context_window": 8192, "max_tokens": 4096, "fallbacks": ["llama-3.3-70b-sambanova", "llama-3.3-70b-groq"]}
        ]}
        save_yaml(default_models, MODELS_PATH)
        
    try:
        cmd_configure()
        log("SUCCESS", "YAML schemas parsed and compiled successfully.")
    except Exception as e:
        log("ERROR", f"Failed to rebuild configuration blueprints: {e}")
        
    # 3. Clean LiteLLM cache
    litellm_cache = os.path.join(os.path.expanduser("~"), ".cache", "litellm")
    if os.path.exists(litellm_cache):
        log("INFO", f"Cleaning LiteLLM cache at {litellm_cache}...")
        try:
            shutil.rmtree(litellm_cache)
            log("SUCCESS", "LiteLLM cache cleaned.")
        except Exception as e:
            log("WARNING", f"Could not clean LiteLLM cache: {e}")
            
    # 4. Check if virtual environment packages are intact
    try:
        import litellm
        log("SUCCESS", "Python package dependencies verified successfully.")
    except ImportError:
        log("WARNING", "LiteLLM python package is missing. Attempting silent reinstall...")
        venv_pip = os.path.join(ROOT_DIR, ".venv", "Scripts", "pip.exe")
        if os.path.exists(venv_pip):
            try:
                subprocess.run([venv_pip, "install", "litellm[proxy]", "pyyaml", "requests"], check=True, capture_output=True)
                log("SUCCESS", "LiteLLM package reinstalled successfully.")
            except Exception as e:
                log("ERROR", f"Failed to run package repair reinstall: {e}")
                
    log("SUCCESS", "Self-healing checks completed.")

def cmd_backup():
    log("INFO", "Creating system configurations backup...")
    settings = load_yaml(SETTINGS_PATH)
    backup_dir = settings.get("lifecycle", {}).get("backup_dir", "backups")
    backup_dir = os.path.abspath(os.path.join(ROOT_DIR, backup_dir))
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(backup_dir, f"openclaw_backup_{timestamp}.zip")
    
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in ["settings.yaml", "providers.yaml", "models.yaml"]:
                fp = os.path.join(CONFIG_DIR, file)
                if os.path.exists(fp):
                    zipf.write(fp, arcname=os.path.join("OpenClawManager", file))
            for file in ["config.yaml", "openclaw.json"]:
                fp = os.path.join(GENERATED_DIR, file)
                if os.path.exists(fp):
                    zipf.write(fp, arcname=os.path.join("generated", file))
            claw_home_dir = settings.get("openclaw", {}).get("config_dir")
            if not claw_home_dir:
                claw_home_dir = os.path.join(os.path.expanduser("~"), ".openclaw")
            claw_json = os.path.join(claw_home_dir, "openclaw.json")
            if os.path.exists(claw_json):
                zipf.write(claw_json, arcname="active_openclaw.json")
        log("SUCCESS", f"Backup archive created successfully: {zip_path}")
        return zip_path
    except Exception as e:
        log("ERROR", f"Failed to create backup: {e}")
        return None

def cmd_restore(backup_idx=None):
    log("INFO", "Running configuration restore interface...")
    settings = load_yaml(SETTINGS_PATH)
    backup_dir = settings.get("lifecycle", {}).get("backup_dir", "backups")
    backup_dir = os.path.abspath(os.path.join(ROOT_DIR, backup_dir))
    
    if not os.path.exists(backup_dir):
        log("ERROR", "No backup directory exists.")
        return False
        
    zips = [f for f in os.listdir(backup_dir) if f.endswith(".zip")]
    if not zips:
        log("ERROR", "No backup zip archives found.")
        return False
        
    if backup_idx is None:
        print("\nAvailable backups:")
        for idx, zip_name in enumerate(zips):
            print(f"[{idx}] {zip_name}")
            
        choice = input("\nSelect backup index to restore (or Enter to cancel): ").strip()
        if not choice or not choice.isdigit():
            log("INFO", "Restore cancelled.")
            return False
        backup_idx = int(choice)
        
    if backup_idx < 0 or backup_idx >= len(zips):
        log("ERROR", f"Invalid backup index: {backup_idx}")
        return False
        
    target_zip = os.path.join(backup_dir, zips[backup_idx])
    log("INFO", f"Restoring from archive: {target_zip}...")
    
    try:
        temp_dir = os.path.join(backup_dir, "temp_restore")
        os.makedirs(temp_dir, exist_ok=True)
        
        with zipfile.ZipFile(target_zip, "r") as zipf:
            # Zip Slip Prevention
            for member in zipf.infolist():
                target_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not target_path.startswith(os.path.abspath(temp_dir)):
                    raise Exception(f"Security Warning: Path traversal detected in zip archive file: {member.filename}")
            zipf.extractall(temp_dir)
            
        for f in ["settings.yaml", "providers.yaml", "models.yaml"]:
            src = os.path.join(temp_dir, "OpenClawManager", f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(CONFIG_DIR, f))
                
        claw_home_dir = settings.get("openclaw", {}).get("config_dir")
        if not claw_home_dir:
            claw_home_dir = os.path.join(os.path.expanduser("~"), ".openclaw")
            
        src_active = os.path.join(temp_dir, "active_openclaw.json")
        if os.path.exists(src_active):
            shutil.copy2(src_active, os.path.join(claw_home_dir, "openclaw.json"))
            
        shutil.rmtree(temp_dir)
        log("SUCCESS", "Configurations successfully restored.")
        cmd_configure()
        return True
    except Exception as e:
        log("ERROR", f"Failed to restore configurations: {e}")
        return False

def cmd_upgrade():
    log("INFO", "Running package upgrade suite...")
    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]
    
    # 1. Upgrade LiteLLM inside virtual environment
    venv_pip = os.path.join(ROOT_DIR, ".venv", "Scripts", "pip.exe")
    if os.path.exists(venv_pip):
        log("INFO", "Upgrading LiteLLM and PyYAML inside .venv...")
        try:
            subprocess.run([venv_pip, "install", "--upgrade", "litellm[proxy]", "pyyaml", "requests"], check=True)
            log("SUCCESS", "LiteLLM upgraded in .venv.")
        except Exception as e:
            log("ERROR", f"Failed to upgrade python packages in .venv: {e}")
            
    # 2. Upgrade OpenClaw globally
    if "npm" in tools:
        log("INFO", "Upgrading OpenClaw globally via npm...")
        try:
            subprocess.run(["npm", "update", "-g", "openclaw"], check=True)
            log("SUCCESS", "OpenClaw package updated.")
        except Exception as e:
            log("ERROR", f"Failed to upgrade OpenClaw via npm: {e}")
            
    cmd_configure()
    log("SUCCESS", "Upgrade completed.")

def cmd_uninstall():
    print("\nWARNING: You are about to uninstall the OpenClaw Workstation package.")
    confirm = input("Are you sure you want to proceed? (yes/no): ").strip().lower()
    if confirm != "yes":
        log("INFO", "Uninstall cancelled.")
        return
        
    log("INFO", "Uninstalling packages...")
    cmd_stop()
    
    venv_dir = os.path.join(ROOT_DIR, ".venv")
    if os.path.exists(venv_dir):
        log("INFO", f"Removing virtual environment directory at {venv_dir}...")
        try:
            shutil.rmtree(venv_dir)
            log("SUCCESS", "Virtual environment removed.")
        except Exception as e:
            log("ERROR", f"Could not remove .venv: {e}")
            
    uninstall_npm = input("Do you want to uninstall openclaw globally from npm? (yes/no): ").strip().lower()
    if uninstall_npm == "yes":
        sys_details = discovery.run_all_discovery(SETTINGS_PATH)
        tools = sys_details["tools"]
        if "npm" in tools:
            log("INFO", "Removing openclaw via npm...")
            try:
                subprocess.run(["npm", "uninstall", "-g", "openclaw"], check=True)
                log("SUCCESS", "OpenClaw npm package uninstalled.")
            except Exception as e:
                log("ERROR", f"Failed to uninstall openclaw npm package: {e}")
                
    remove_configs = input("Do you want to remove generated and local configurations (~/.openclaw)? (yes/no): ").strip().lower()
    if remove_configs == "yes":
        if os.path.exists(GENERATED_DIR):
            shutil.rmtree(GENERATED_DIR)
        claw_home = os.path.join(os.path.expanduser("~"), ".openclaw")
        if os.path.exists(claw_home):
            shutil.rmtree(claw_home)
        log("SUCCESS", "Configuration files removed.")
        
    log("SUCCESS", "Uninstall complete.")

def main():
    parser = argparse.ArgumentParser(description="OpenClaw Workstation Lifecycle Manager CLI")
    parser.add_argument("command", choices=[
        "install", "configure", "start", "stop", "status", "diagnose", "repair", "backup", "restore", "upgrade", "uninstall"
    ], help="Command to run")
    
    args = parser.parse_args()
    
    if args.command == "install":
        cmd_install()
    elif args.command == "configure":
        cmd_configure()
    elif args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "diagnose":
        cmd_diagnose()
    elif args.command == "repair":
        cmd_repair()
    elif args.command == "backup":
        cmd_backup()
    elif args.command == "restore":
        cmd_restore()
    elif args.command == "upgrade":
        cmd_upgrade()
    elif args.command == "uninstall":
        cmd_uninstall()

if __name__ == "__main__":
    main()
