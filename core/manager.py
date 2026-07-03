# core/manager.py
# Unified Lifecyle Management Engine for OpenClaw Workstation

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
LITELLM_SETTINGS_PATH = os.path.join(GENERATED_DIR, "litellm.yaml")
OPENCLAW_CONFIG_PATH = os.path.join(GENERATED_DIR, "openclaw.json")

# Ensure folders exist
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Logger setup
LOG_FILE = os.path.join(LOGS_DIR, "installer.log")

def log(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_msg = message
    # Secrets masking (generic regex for API keys: e.g., sk-... or similar)
    clean_msg = re.sub(r'(sk-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+', r'\1...', clean_msg)
    clean_msg = re.sub(r'(nvapi-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+', r'\1...', clean_msg)
    
    # Print to console with colors
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
    
    # Write to file
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{level}] {clean_msg}\n")
    except Exception:
        pass

# Safe YAML Loader (simplistic fallback to prevent library import errors)
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

def load_yaml(path):
    if not os.path.exists(path):
        return {}
    if HAS_YAML:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    else:
        # Simplistic parser for basic values in case yaml library is loading
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
        # Fallback simplistic dumper
        with open(path, "w", encoding="utf-8") as f:
            for k, v in data.items():
                if isinstance(v, dict):
                    f.write(f"{k}:\n")
                    for subk, subv in v.items():
                        f.write(f"  {subk}: {json.dumps(subv)}\n")
                else:
                    f.write(f"{k}: {json.dumps(v)}\n")

# --- Helper functions for Windows Process Scavenging ---

def get_pids_on_port(port):
    """Find process IDs using a specific TCP port on Windows."""
    pids = set()
    try:
        res = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=True)
        # Looking for ":port  *   LISTENING   PID"
        # Example: TCP    127.0.0.1:4000         0.0.0.0:0              LISTENING       1234
        pattern = re.compile(rf":{port}\s+\S+\s+LISTENING\s+(\d+)")
        for line in res.stdout.splitlines():
            m = pattern.search(line)
            if m:
                pids.add(int(m.group(1)))
    except Exception as e:
        log("WARNING", f"Could not list TCP connections: {e}")
    return list(pids)

def is_pid_alive(pid):
    """Check if a process ID is currently running on the system."""
    try:
        res = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in res.stdout
    except Exception:
        return False

def kill_process_tree(pid):
    """Gracefully terminate a process tree on Windows, falling back to force kill if unresponsive."""
    try:
        log("INFO", f"Attempting graceful shutdown of PID {pid} and its children...")
        # Try graceful termination first (taskkill without /F)
        subprocess.run(["taskkill", "/T", "/PID", str(pid)], capture_output=True)
        
        # Wait up to 3 seconds for the process to exit
        for _ in range(3):
            time.sleep(1)
            if not is_pid_alive(pid):
                log("SUCCESS", f"Process PID {pid} exited gracefully.")
                return True
                
        # Force-kill fallback if process is still running
        log("WARNING", f"PID {pid} did not respond. Initiating force kill...")
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=True)
        log("SUCCESS", f"Successfully force-killed PID {pid}.")
        return True
    except subprocess.CalledProcessError as e:
        log("WARNING", f"Could not kill PID {pid}: {e.stderr.strip() if e.stderr else str(e)}")
        return False

def scavenge_ports(ports):
    """Find and kill processes on ports."""
    for port in ports:
        pids = get_pids_on_port(port)
        if pids:
            log("WARNING", f"Port {port} is occupied by PIDs: {pids}")
            for pid in pids:
                kill_process_tree(pid)
        else:
            log("INFO", f"Port {port} is free.")

# --- System Discovery ---

def get_username():
    return os.environ.get("USERNAME", "default")

def get_user_home():
    return os.path.expanduser("~")

def detect_gpu():
    """Detect presence of NVIDIA GPU on Windows."""
    try:
        res = subprocess.run(["wmic", "path", "win32_VideoController", "get", "name"], capture_output=True, text=True)
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip() and "Name" not in line]
        gpu_str = " / ".join(lines)
        is_nvidia = "nvidia" in gpu_str.lower()
        return is_nvidia, gpu_str
    except Exception:
        return False, "Unknown GPU"

def discover_tools():
    """Detect presence and paths of vital installer tools."""
    tools = {}
    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        try:
            path = shutil.which(tool)
            if path:
                tools[tool] = path
            else:
                # Custom check for common paths on Windows
                if tool == "python":
                    for p in ["C:\\Python314\\python.exe", "C:\\Python313\\python.exe", "C:\\Python312\\python.exe", "C:\\Python311\\python.exe"]:
                        if os.path.exists(p):
                            tools[tool] = p
                            break
                elif tool == "node" and os.path.exists("C:\\Program Files\\nodejs\\node.exe"):
                    tools[tool] = "C:\\Program Files\\nodejs\\node.exe"
                elif tool == "npm" and os.path.exists("C:\\Program Files\\nodejs\\npm.cmd"):
                    tools[tool] = "C:\\Program Files\\nodejs\\npm.cmd"
                elif tool == "uv" and os.path.exists(os.path.join(get_user_home(), ".local", "bin", "uv.exe")):
                    tools[tool] = os.path.join(get_user_home(), ".local", "bin", "uv.exe")
                elif tool == "ollama":
                    for p in [os.path.join(os.environ.get("LocalAppData", ""), "Programs", "Ollama", "ollama.exe"), "C:\\Program Files\\Ollama\\ollama.exe"]:
                        if os.path.exists(p):
                            tools[tool] = p
                            break
        except Exception:
            pass
    return tools

# --- Ollama Support ---

def query_ollama_models(api_base):
    try:
        url = f"{api_base.rstrip('/')}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            return [m['name'] for m in data.get('models', [])]
    except Exception as e:
        log("WARNING", f"Could not connect to Ollama api: {e}")
        return []

def start_ollama_if_needed(tools, api_base):
    """Start Ollama if installed but not running."""
    models = query_ollama_models(api_base)
    if models:
        return models
    
    if "ollama" in tools:
        log("INFO", "Ollama is installed but not running. Launching Ollama serve...")
        try:
            subprocess.Popen([tools["ollama"], "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Wait up to 5 seconds for Ollama to spin up
            for _ in range(5):
                time.sleep(1)
                models = query_ollama_models(api_base)
                if models:
                    log("SUCCESS", "Ollama started successfully.")
                    return models
        except Exception as e:
            log("WARNING", f"Could not start Ollama: {e}")
    return []

# --- API Key Management (Security) ---

def get_windows_env(name):
    """Get persistent User Environment Variable from Windows registry/API."""
    try:
        # Run PowerShell command to extract persistent user variable
        cmd = f"[System.Environment]::GetEnvironmentVariable('{name}', 'User')"
        res = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True, check=True)
        val = res.stdout.strip()
        if val:
            return val
    except Exception:
        pass
    # Fallback to current process env
    return os.environ.get(name)

def set_windows_env(name, value):
    """Save persistent User Environment Variable to Windows."""
    try:
        # Run PowerShell command to write persistent user variable
        cmd = f"[System.Environment]::SetEnvironmentVariable('{name}', '{value}', 'User')"
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, check=True)
        # Also set it in current process
        os.environ[name] = value
        return True
    except Exception as e:
        log("ERROR", f"Failed to save environment variable {name}: {e}")
        return False

def validate_provider_key(provider, key):
    """Validate API key format and length (simple client-side check)."""
    if not key or len(key.strip()) < 8:
        return False
    # Specific formats check
    if provider == "gemini" and not (key.startswith("AIzaSy") or len(key) >= 35):
         return False
    if provider == "groq" and not (key.startswith("gsk_") or len(key) >= 40):
         return False
    return True

# --- Commands Execution ---

def cmd_install():
    log("INFO", "Running installation and interactive setup...")
    
    # 1. Load providers
    providers = load_yaml(PROVIDERS_PATH)
    if not providers:
        log("ERROR", "providers.yaml not found or corrupted.")
        sys.exit(1)
        
    configured = 0
    skipped = 0
    
    # Enable environment variables migration check
    gemini_key = get_windows_env("GEMINI_API_KEY")
    if not gemini_key:
        google_key = get_windows_env("GOOGLE_API_KEY")
        if google_key:
            log("INFO", "Auto-migrating GOOGLE_API_KEY to GEMINI_API_KEY...")
            set_windows_env("GEMINI_API_KEY", google_key)
            gemini_key = google_key

    for p_name, p_info in providers.items():
        if not p_info.get("enabled", False):
            continue
            
        env_var = p_info.get("env_var")
        current_val = get_windows_env(env_var)
        
        if current_val:
            log("SUCCESS", f"Provider {p_name} ({env_var}) is already configured.")
            configured += 1
        else:
            print(f"\n[{p_name.upper()}] Missing API Key ({env_var})")
            print(f"  Info: {p_info.get('info')}")
            key_input = input(f"  Please enter API Key for {p_name} (or press Enter to skip): ").strip()
            
            if key_input:
                if validate_provider_key(p_name, key_input):
                    set_windows_env(env_var, key_input)
                    log("SUCCESS", f"Saved {env_var} to Windows User Environment Variables.")
                    configured += 1
                else:
                    log("WARNING", f"Key entered for {p_name} looks invalid. Skipped.")
                    skipped += 1
            else:
                log("INFO", f"Skipped {p_name}.")
                skipped += 1
                
    log("INFO", f"Installation setup finished. Configured: {configured}, Skipped: {skipped}")
    
    # Run configuration generation
    cmd_configure()

def cmd_configure():
    log("INFO", "Generating runtime configurations...")
    
    # 1. Load input configs
    settings = load_yaml(SETTINGS_PATH)
    providers = load_yaml(PROVIDERS_PATH)
    models_reg = load_yaml(MODELS_PATH)
    
    if not settings or not providers or not models_reg:
        log("ERROR", "Missing settings.yaml, providers.yaml, or models.yaml.")
        sys.exit(1)
        
    tools = discover_tools()
    
    # 2. Check Ollama
    ollama_enabled = settings.get("ollama", {}).get("enabled", True)
    ollama_api = settings.get("ollama", {}).get("api_base", "http://127.0.0.1:11434")
    ollama_autostart = settings.get("ollama", {}).get("autostart", True)
    
    ollama_models = []
    if ollama_enabled:
        if ollama_autostart:
            ollama_models = start_ollama_if_needed(tools, ollama_api)
        else:
            ollama_models = query_ollama_models(ollama_api)
            
        if ollama_models:
            log("SUCCESS", f"Auto-discovered Ollama models: {ollama_models}")
        else:
            log("INFO", "No Ollama models found or Ollama is offline.")
            
    # 3. Compile LiteLLM config.yaml
    litellm_model_list = []
    active_fallbacks = {}
    
    # Build models from models.yaml (Pass 1: Identify active models)
    active_model_ids = set()
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        
        # Check if provider is enabled
        if p_cfg.get("enabled", False):
            env_var = p_cfg.get("env_var")
            # Verify if API Key exists
            if get_windows_env(env_var):
                model_entry = {
                    "model_name": m.get("id"),
                    "litellm_params": {
                        "model": m.get("litellm_model"),
                        "api_key": f"os.environ/{env_var}"
                    }
                }
                litellm_model_list.append(model_entry)
                active_model_ids.add(m.get("id"))
            else:
                log("WARNING", f"Model {m.get('id')} skipped (API key {env_var} not configured).")
                
    # Append Ollama models dynamically and add to active list
    for om in ollama_models:
        ollama_id = f"ollama/{om}"
        model_entry = {
            "model_name": ollama_id,
            "litellm_params": {
                "model": ollama_id,
                "api_base": ollama_api
            }
        }
        litellm_model_list.append(model_entry)
        active_model_ids.add(ollama_id)
        
    # Pass 2: Populate fallbacks, filtering out disabled or unconfigured models
    for m in models_reg.get("models", []):
        model_id = m.get("id")
        if model_id in active_model_ids and m.get("fallbacks"):
            filtered_fbs = [fb for fb in m.get("fallbacks") if fb in active_model_ids]
            if filtered_fbs:
                active_fallbacks[model_id] = filtered_fbs
        
    # Build full LiteLLM proxy configuration dictionary
    litellm_config = {
        "model_list": litellm_model_list,
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
    
    # Save LiteLLM config.yaml
    save_yaml(litellm_config, LITELLM_CONFIG_PATH)
    log("SUCCESS", f"Generated LiteLLM Proxy configuration: {LITELLM_CONFIG_PATH}")
    
    # 4. Compile OpenClaw openclaw.json configuration
    openclaw_models = []
    
    # Base models from models.yaml
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        if providers.get(provider, {}).get("enabled", False) and get_windows_env(providers.get(provider, {}).get("env_var")):
            openclaw_models.append({
                "id": m.get("id"),
                "name": m.get("name"),
                "contextWindow": m.get("context_window", 4096),
                "maxTokens": m.get("max_tokens", 4096)
            })
            
    # Ollama models
    for om in ollama_models:
        openclaw_models.append({
            "id": f"ollama/{om}",
            "name": f"{om} (Ollama)",
            "contextWindow": 4096,
            "maxTokens": 4096
        })
        
    litellm_api_key = settings.get("litellm", {}).get("api_key", "sk-litellm-key")
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
    
    # Save dynamic OpenClaw config to generated directory
    with open(OPENCLAW_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(openclaw_cfg, f, indent=2)
    log("SUCCESS", f"Generated OpenClaw gateway configuration: {OPENCLAW_CONFIG_PATH}")
    
    # 5. Non-destructive merge with active user openclaw.json (~/.openclaw/openclaw.json)
    claw_dir = settings.get("openclaw", {}).get("config_dir")
    if not claw_dir:
        claw_dir = os.path.join(get_user_home(), ".openclaw")
        
    os.makedirs(claw_dir, exist_ok=True)
    active_claw_path = os.path.join(claw_dir, "openclaw.json")
    
    existing_claw_data = {}
    if os.path.exists(active_claw_path):
        # Back it up first
        backup_active = active_claw_path + ".bak"
        shutil.copy2(active_claw_path, backup_active)
        log("INFO", f"Backed up active OpenClaw config to {backup_active}")
        
        try:
            with open(active_claw_path, "r", encoding="utf-8") as f:
                existing_claw_data = json.load(f)
        except Exception as e:
            log("WARNING", f"Existing openclaw.json was corrupted. Merging with default schema. Error: {e}")
            
    # Merge sections
    # Keep existing plugins, tools, session, skills, env, gateway etc.
    # Overwrite only the models provider list and agents default models
    import secrets
    # Ensure secure gateway token is generated dynamically
    if "gateway" not in existing_claw_data:
        existing_claw_data["gateway"] = {
            "auth": {
                "mode": "token",
                "token": secrets.token_hex(24)
            },
            "bind": "loopback",
            "mode": "local",
            "port": settings.get("openclaw", {}).get("port", 18789)
        }
    else:
        # If the gateway exists, check if it uses the default static insecure token
        auth = existing_claw_data["gateway"].get("auth", {})
        if auth.get("token") == "7d07bed5a8d8621d4dab6bec133d7297e58f915902437007":
            log("WARNING", "Insecure static default token detected. Upgrading to dynamically generated token...")
            if "auth" not in existing_claw_data["gateway"]:
                existing_claw_data["gateway"]["auth"] = {}
            existing_claw_data["gateway"]["auth"]["token"] = secrets.token_hex(24)
        
    # Setup LiteLLM provider block
    if "models" not in existing_claw_data:
        existing_claw_data["models"] = {}
    if "providers" not in existing_claw_data["models"]:
        existing_claw_data["models"]["providers"] = {}
        
    existing_claw_data["models"]["providers"]["litellm"] = openclaw_cfg["models"]["providers"]["litellm"]
    
    # Setup agents defaults
    if "agents" not in existing_claw_data:
        existing_claw_data["agents"] = {}
    if "defaults" not in existing_claw_data["agents"]:
        existing_claw_data["agents"]["defaults"] = {}
        
    # Set primary model and fallbacks dynamically based on enabled models
    primary_model = "litellm/gemini-2.5-flash"
    fallbacks = []
    
    active_ids = [m.get("id") for m in openclaw_models]
    if active_ids:
        # Pick the first active model as primary
        primary_model = f"litellm/{active_ids[0]}"
        # The rest are fallbacks
        fallbacks = [f"litellm/{aid}" for aid in active_ids[1:]]
        
    existing_claw_data["agents"]["defaults"]["model"] = {
        "primary": primary_model,
        "fallbacks": fallbacks
    }
    
    # Populate the defaults.models list
    agent_models = {}
    for aid in active_ids:
        agent_models[f"litellm/{aid}"] = {}
    existing_claw_data["agents"]["defaults"]["models"] = agent_models
    
    if "workspace" not in existing_claw_data["agents"]["defaults"]:
        existing_claw_data["agents"]["defaults"]["workspace"] = os.path.join(claw_dir, "workspace")
        
    # Write back to active openclaw.json
    try:
        with open(active_claw_path, "w", encoding="utf-8") as f:
            json.dump(existing_claw_data, f, indent=2)
        log("SUCCESS", f"Successfully updated active OpenClaw config at {active_claw_path}")
    except Exception as e:
        log("ERROR", f"Failed to write to active openclaw.json: {e}")
        # Rollback
        if os.path.exists(active_claw_path + ".bak"):
            shutil.copy2(active_claw_path + ".bak", active_claw_path)
            log("INFO", "Rolled back active OpenClaw config from backup.")

def cmd_start():
    log("INFO", "Starting OpenClaw workstation stack...")
    
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    litellm_key = settings.get("litellm", {}).get("api_key", "sk-litellm-key")
    
    # 1. Run scavenger to release ports if configured
    if settings.get("lifecycle", {}).get("auto_cleanup_ports", True):
        log("INFO", "Checking ports and cleaning up dangling processes...")
        scavenge_ports([litellm_port, openclaw_port])
        
    # 2. Re-compile configurations
    cmd_configure()
    
    # 3. Setup environments
    os.environ["LITELLM_API_KEY"] = litellm_key
    os.environ["OPENCLAW_GATEWAY_PORT"] = str(openclaw_port)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    
    # Make sure all API keys are passed to the start environment
    providers = load_yaml(PROVIDERS_PATH)
    for p_name, p_info in providers.items():
        if p_info.get("enabled", False):
            var = p_info.get("env_var")
            val = get_windows_env(var)
            if val:
                os.environ[var] = val

    # 4. Launch LiteLLM Proxy in background
    log("INFO", f"Launching LiteLLM Proxy on port {litellm_port}...")
    venv_litellm = os.path.join(ROOT_DIR, ".venv", "Scripts", "litellm.exe")
    if os.path.exists(venv_litellm):
        executable = venv_litellm
        litellm_args = [executable, "--config", LITELLM_CONFIG_PATH, "--port", str(litellm_port)]
    else:
        venv_python = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
        if not os.path.exists(venv_python):
            venv_python = "python"
        executable = venv_python
        litellm_args = [executable, "-m", "litellm", "--config", LITELLM_CONFIG_PATH, "--port", str(litellm_port)]
    
    litellm_log_file = open(os.path.join(LOGS_DIR, "litellm.log"), "w", encoding="utf-8")
    
    try:
        litellm_proc = subprocess.Popen(
            litellm_args,
            stdout=litellm_log_file,
            stderr=litellm_log_file,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )
    except Exception as e:
        log("ERROR", f"Failed to spawn LiteLLM process: {e}")
        sys.exit(1)
        
    # 5. Poll LiteLLM readiness
    log("INFO", "Waiting for LiteLLM Proxy readiness...")
    ready = False
    readiness_url = f"http://localhost:{litellm_port}/health/readiness"
    for i in range(30):
        try:
            req = urllib.request.Request(readiness_url)
            with urllib.request.urlopen(req, timeout=1) as response:
                content = response.read().decode().lower()
                if "healthy" in content:
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if ready:
        log("SUCCESS", "LiteLLM Proxy is online and healthy!")
    else:
        log("WARNING", "LiteLLM Proxy did not report ready in time. Attempting to start OpenClaw anyway...")
        
    # 6. Launch OpenClaw Gateway
    log("INFO", f"Launching OpenClaw Gateway on port {openclaw_port}...")
    
    tools = discover_tools()
    node_exe = tools.get("node", "node.exe")
    
    # Locate OpenClaw index.js (Local first, then Global AppData, then global node_modules)
    local_dist = os.path.join(ROOT_DIR, "node_modules", "openclaw", "dist", "index.js")
    global_appdata_dist = os.path.join(os.environ.get("AppData", ""), "npm", "node_modules", "openclaw", "dist", "index.js")
    global_program_files_dist = os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", "node_modules", "openclaw", "dist", "index.js")
    
    openclaw_dist = None
    if os.path.exists(local_dist):
        openclaw_dist = local_dist
        log("INFO", f"Found local OpenClaw installation at: {local_dist}")
    elif os.path.exists(global_appdata_dist):
        openclaw_dist = global_appdata_dist
        log("INFO", f"Found global AppData OpenClaw installation at: {global_appdata_dist}")
    elif os.path.exists(global_program_files_dist):
        openclaw_dist = global_program_files_dist
        log("INFO", f"Found global Program Files OpenClaw installation at: {global_program_files_dist}")

    if not openclaw_dist:
        # Fallback to simple command execution via system PATH
        openclaw_args = ["openclaw", "gateway", "--port", str(openclaw_port)]
        executable = "cmd.exe"
        openclaw_args = ["/c"] + openclaw_args
        log("INFO", "OpenClaw package index.js not found in directories; executing from system PATH.")
    else:
        executable = node_exe
        openclaw_args = [openclaw_dist, "gateway", "--port", str(openclaw_port)]
        
    log("INFO", f"Running OpenClaw Gateway. Press Ctrl+C to terminate both servers.")
    print("--------------------------------------------------------------------------------")
    
    try:
        # Run OpenClaw in the foreground
        subprocess.run([executable] + openclaw_args, check=True)
    except KeyboardInterrupt:
        print("\n--------------------------------------------------------------------------------")
        log("INFO", "Shutting down servers...")
    except Exception as e:
        log("ERROR", f"OpenClaw execution error: {e}")
    finally:
        # Terminate LiteLLM Proxy
        if litellm_proc.poll() is None:
            log("INFO", f"Stopping LiteLLM Proxy (PID: {litellm_proc.pid})...")
            kill_process_tree(litellm_proc.pid)
        litellm_log_file.close()
        log("SUCCESS", "Servers stopped cleanly.")

def cmd_stop():
    log("INFO", "Stopping all OpenClaw workstation components...")
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    scavenge_ports([litellm_port, openclaw_port])
    log("SUCCESS", "Components stopped.")

def cmd_status():
    log("INFO", "Retrieving stack status...")
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    
    l_pids = get_pids_on_port(litellm_port)
    c_pids = get_pids_on_port(openclaw_port)
    
    print("\n==============================================")
    print("   OpenClaw Workstation Status Dashboard")
    print("==============================================")
    if l_pids:
        print(f"LiteLLM Proxy:     ONLINE (Port: {litellm_port}, PIDs: {l_pids})")
    else:
        print(f"LiteLLM Proxy:     OFFLINE (Port: {litellm_port})")
        
    if c_pids:
        print(f"OpenClaw Gateway:  ONLINE (Port: {openclaw_port}, PIDs: {c_pids})")
    else:
        print(f"OpenClaw Gateway:  OFFLINE (Port: {openclaw_port})")
    print("==============================================")

def cmd_diagnose():
    log("INFO", "Running workstation diagnostic tests...")
    
    settings = load_yaml(SETTINGS_PATH)
    providers = load_yaml(PROVIDERS_PATH)
    models_reg = load_yaml(MODELS_PATH)
    
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    litellm_key = settings.get("litellm", {}).get("api_key", "sk-litellm-key")
    
    # 1. Dependency checks
    tools = discover_tools()
    is_nvidia, gpu_name = detect_gpu()
    
    diagnostics = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "os": f"{platform.system()} {platform.release()}",
        "gpu": gpu_name,
        "tools": tools,
        "models": []
    }
    
    # 2. Check LiteLLM running status
    litellm_online = len(get_pids_on_port(litellm_port)) > 0
    if not litellm_online:
        log("ERROR", f"LiteLLM Proxy is not running on port {litellm_port}. Cannot run API diagnostics.")
        log("INFO", "Please start the gateway first before running diagnostics.")
        sys.exit(1)
        
    # 3. Model validation and benchmarking
    log("INFO", "Benchmarking model completion latencies...")
    
    active_models = []
    # Load all models that should be compiled
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        if p_cfg.get("enabled", False) and get_windows_env(p_cfg.get("env_var")):
            active_models.append(m)
            
    # Add Ollama models if any
    ollama_api = settings.get("ollama", {}).get("api_base", "http://127.0.0.1:11434")
    ollama_models = query_ollama_models(ollama_api)
    for om in ollama_models:
        active_models.append({
            "id": f"ollama/{om}",
            "name": f"{om} (Ollama)",
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
        
        log("INFO", f"Testing completion for model: {friendly_name} ({model_id})...")
        
        body = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Respond with only one word: hello"}],
            "max_tokens": 5
        }
        
        start_time = time.perf_counter()
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
            with urllib.request.urlopen(req, timeout=15) as res:
                end_time = time.perf_counter()
                latency = int((end_time - start_time) * 1000)
                res_data = json.loads(res.read().decode())
                response_text = res_data['choices'][0]['message']['content'].strip()
                success = True
                log("SUCCESS", f"  Received response in {latency}ms: '{response_text}'")
        except urllib.error.HTTPError as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            try:
                error_msg = e.read().decode()
                # Try to parse json error
                err_json = json.loads(error_msg)
                if 'error' in err_json and 'message' in err_json['error']:
                    error_msg = err_json['error']['message']
            except Exception:
                error_msg = str(e)
            log("ERROR", f"  Request failed: {error_msg}")
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
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
        
    # Generate reports
    generate_reports(diagnostics)

def generate_reports(diagnostics):
    """Write health report outputs in Markdown and HTML formats."""
    md_path = os.path.join(GENERATED_DIR, "health-report.md")
    html_path = os.path.join(GENERATED_DIR, "health-report.html")
    
    # 1. Generate Markdown Report
    md = []
    md.append("# OpenClaw Workstation Health & Diagnostics Report")
    md.append(f"\n**Checked at:** {diagnostics['timestamp']}")
    md.append(f"\n**OS Platform:** {diagnostics['os']}")
    md.append(f"**GPU Hardware:** {diagnostics['gpu']}")
    
    md.append("\n## System Dependency Discovery")
    md.append("| Dependency | Status | Executable Path |")
    md.append("| :--- | :--- | :--- |")
    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        status = "FOUND" if tool in diagnostics["tools"] else "MISSING"
        path = diagnostics["tools"].get(tool, "N/A")
        md.append(f"| {tool.upper()} | {status} | `{path}` |")
        
    md.append("\n## Endpoint Latency & Benchmark Registry")
    md.append("| Provider / Model | Status | Latency (ms) | Output / Error Message |")
    md.append("| :--- | :--- | :--- | :--- |")
    
    for m in diagnostics["models"]:
        status = "HEALTHY" if m["success"] else "FAILED"
        latency = f"{m['latency_ms']} ms" if m["success"] else "N/A"
        msg = f"Response: '{m['response']}'" if m["success"] else f"Error: {m['error']}"
        md.append(f"| {m['name']} (`{m['id']}`) | {status} | {latency} | {msg} |")
        
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    log("SUCCESS", f"Markdown diagnostic report compiled: {md_path}")
    
    # 2. Generate HTML Report (Beautiful premium dark mode)
    html = []
    html.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Workstation Diagnostics</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --accent: #3b82f6;
            --success: #10b981;
            --error: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
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
            padding: 2.5rem 1.5rem;
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            margin-bottom: 2.5rem;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 1.5rem;
        }
        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(to right, #60a5fa, #3b82f6, #2563eb);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        .meta-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2.5rem;
        }
        .meta-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 1.25rem;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
        }
        .meta-label {
            font-size: 0.875rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.25rem;
        }
        .meta-value {
            font-size: 1.25rem;
            font-weight: 600;
        }
        h2 {
            font-size: 1.75rem;
            margin-bottom: 1.25rem;
            font-weight: 600;
        }
        .dep-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 2.5rem;
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            overflow: hidden;
        }
        .dep-table th, .dep-table td {
            padding: 1rem 1.25rem;
            text-align: left;
        }
        .dep-table th {
            background-color: #1e293b;
            font-weight: 600;
            border-bottom: 1px solid var(--card-border);
        }
        .dep-table tr:not(:last-child) {
            border-bottom: 1px solid var(--card-border);
        }
        .badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 9999px;
            text-transform: uppercase;
        }
        .badge-found {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--success);
        }
        .badge-missing {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--error);
        }
        .model-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 1.5rem;
        }
        .model-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 1.5rem;
            position: relative;
            overflow: hidden;
            transition: transform 0.2s, border-color 0.2s;
        }
        .model-card:hover {
            transform: translateY(-2px);
            border-color: var(--accent);
        }
        .model-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1rem;
        }
        .model-name {
            font-size: 1.25rem;
            font-weight: 600;
        }
        .model-id {
            font-size: 0.875rem;
            color: var(--text-muted);
            font-family: monospace;
        }
        .latency-value {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--accent);
            margin: 0.75rem 0;
        }
        .error-box {
            background-color: rgba(239, 68, 68, 0.08);
            border: 1px solid rgba(239, 68, 68, 0.2);
            color: #fca5a5;
            padding: 0.75rem;
            border-radius: 8px;
            font-size: 0.875rem;
            margin-top: 0.75rem;
            font-family: monospace;
            word-break: break-all;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>OpenClaw Workstation Diagnostics</h1>
            <p style="color: var(--text-muted)">System Integrity & Provider Connection Dashboard</p>
        </header>

        <div class="meta-grid">""")
        
    html.append(f"""
            <div class="meta-card">
                <div class="meta-label">Checked Timestamp</div>
                <div class="meta-value">{diagnostics['timestamp']}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">OS Platform</div>
                <div class="meta-value">{diagnostics['os']}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">Graphics Hardware</div>
                <div class="meta-value">{diagnostics['gpu']}</div>
            </div>
    """)
    
    html.append("""
        </div>

        <h2>Dependencies Status</h2>
        <table class="dep-table">
            <thead>
                <tr>
                    <th>Executable / Package</th>
                    <th>Availability</th>
                    <th>Target Path</th>
                </tr>
            </thead>
            <tbody>""")
            
    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        status = "FOUND" if tool in diagnostics["tools"] else "MISSING"
        badge_class = "badge-found" if tool in diagnostics["tools"] else "badge-missing"
        path = diagnostics["tools"].get(tool, "N/A")
        html.append(f"""
                <tr>
                    <td><strong>{tool.upper()}</strong></td>
                    <td><span class="badge {badge_class}">{status}</span></td>
                    <td><code>{path}</code></td>
                </tr>""")
                
    html.append("""
            </tbody>
        </table>

        <h2>Endpoints Latency Benchmarks</h2>
        <div class="model-grid">""")
        
    for m in diagnostics["models"]:
        badge_class = "badge-found" if m["success"] else "badge-missing"
        status_txt = "Healthy" if m["success"] else "Failed"
        latency_txt = f"{m['latency_ms']} ms" if m["success"] else "Offline"
        
        html.append(f"""
            <div class="model-card">
                <div class="model-header">
                    <div>
                        <div class="model-name">{m['name']}</div>
                        <div class="model-id">{m['id']}</div>
                    </div>
                    <span class="badge {badge_class}">{status_txt}</span>
                </div>
                <div class="latency-value">{latency_txt}</div>""")
                
        if m["success"]:
            html.append(f"""
                <div style="font-size: 0.875rem; color: var(--text-muted)">
                    Response: <span style="color: var(--text-main); font-style: italic">"{m['response']}"</span>
                </div>
            """)
        else:
            html.append(f"""
                <div class="error-box">{m['error']}</div>
            """)
            
        html.append("</div>")
        
    html.append("""
        </div>
    </div>
</body>
</html>""")
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    log("SUCCESS", f"HTML diagnostic report compiled: {html_path}")

def cmd_repair():
    log("INFO", "Executing self-healing routine...")
    
    settings = load_yaml(SETTINGS_PATH)
    litellm_port = settings.get("litellm", {}).get("port", 4000)
    openclaw_port = settings.get("openclaw", {}).get("port", 18789)
    
    # 1. Kill stale processes holding ports
    log("INFO", "Port Auditing: scavenge occupied gateway ports...")
    scavenge_ports([litellm_port, openclaw_port])
    
    # 2. Check and regenerate configuration files
    log("INFO", "Configuration Auditing: checking configuration file schemas...")
    
    # Regenerate configs
    try:
        cmd_configure()
        log("SUCCESS", "YAML schemas parsed and compiled successfully.")
    except Exception as e:
        log("ERROR", f"Failed to rebuild configuration files: {e}")
        
    # 3. Clean LiteLLM cache
    litellm_cache = os.path.join(get_user_home(), ".cache", "litellm")
    if os.path.exists(litellm_cache):
        log("INFO", f"Cleaning LiteLLM cache at {litellm_cache}...")
        try:
            shutil.rmtree(litellm_cache)
            log("SUCCESS", "LiteLLM cache cleaned.")
        except Exception as e:
            log("WARNING", f"Could not clean LiteLLM cache: {e}")
            
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
            # Backup OpenClawManager YAML files
            for file in ["settings.yaml", "providers.yaml", "models.yaml"]:
                fp = os.path.join(CONFIG_DIR, file)
                if os.path.exists(fp):
                    zipf.write(fp, arcname=os.path.join("OpenClawManager", file))
            
            # Backup generated files
            for file in ["config.yaml", "openclaw.json"]:
                fp = os.path.join(GENERATED_DIR, file)
                if os.path.exists(fp):
                    zipf.write(fp, arcname=os.path.join("generated", file))
                    
            # Backup active home folder config
            claw_home_dir = settings.get("openclaw", {}).get("config_dir")
            if not claw_home_dir:
                claw_home_dir = os.path.join(get_user_home(), ".openclaw")
            claw_json = os.path.join(claw_home_dir, "openclaw.json")
            if os.path.exists(claw_json):
                zipf.write(claw_json, arcname="active_openclaw.json")
                
        log("SUCCESS", f"Backup archive created successfully: {zip_path}")
    except Exception as e:
        log("ERROR", f"Failed to create backup: {e}")

def cmd_restore():
    log("INFO", "Running configuration restore interface...")
    settings = load_yaml(SETTINGS_PATH)
    backup_dir = settings.get("lifecycle", {}).get("backup_dir", "backups")
    backup_dir = os.path.abspath(os.path.join(ROOT_DIR, backup_dir))
    
    if not os.path.exists(backup_dir):
        log("ERROR", "No backup directory exists.")
        return
        
    zips = [f for f in os.listdir(backup_dir) if f.endswith(".zip")]
    if not zips:
        log("ERROR", "No backup zip archives found.")
        return
        
    print("\nAvailable backups:")
    for idx, zip_name in enumerate(zips):
        print(f"[{idx}] {zip_name}")
        
    choice = input("\nSelect backup index to restore (or Enter to cancel): ").strip()
    if not choice or not choice.isdigit():
        log("INFO", "Restore cancelled.")
        return
        
    idx = int(choice)
    if idx < 0 or idx >= len(zips):
        log("ERROR", "Invalid choice.")
        return
        
    target_zip = os.path.join(backup_dir, zips[idx])
    log("INFO", f"Restoring from archive: {target_zip}...")
    
    try:
        # Create temp folder
        temp_dir = os.path.join(backup_dir, "temp_restore")
        os.makedirs(temp_dir, exist_ok=True)
        
        with zipfile.ZipFile(target_zip, "r") as zipf:
            # Zip Slip Prevention: Verify all extraction paths stay inside target directory
            for member in zipf.infolist():
                target_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not target_path.startswith(os.path.abspath(temp_dir)):
                    raise Exception(f"Security Warning: Path traversal detected in zip archive file: {member.filename}")
            zipf.extractall(temp_dir)
            
        # Copy config folder files
        for f in ["settings.yaml", "providers.yaml", "models.yaml"]:
            src = os.path.join(temp_dir, "OpenClawManager", f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(CONFIG_DIR, f))
                
        # Copy active config file back
        claw_home_dir = settings.get("openclaw", {}).get("config_dir")
        if not claw_home_dir:
            claw_home_dir = os.path.join(get_user_home(), ".openclaw")
        
        src_active = os.path.join(temp_dir, "active_openclaw.json")
        if os.path.exists(src_active):
            shutil.copy2(src_active, os.path.join(claw_home_dir, "openclaw.json"))
            
        # Cleanup temp
        shutil.rmtree(temp_dir)
        log("SUCCESS", "System configurations successfully restored.")
        
        # Regenerate configs
        cmd_configure()
    except Exception as e:
        log("ERROR", f"Failed to restore configurations: {e}")

def cmd_upgrade():
    log("INFO", "Running package upgrade suite...")
    
    tools = discover_tools()
    
    # 1. Upgrade LiteLLM inside virtual environment
    venv_pip = os.path.join(ROOT_DIR, ".venv", "Scripts", "pip.exe")
    if os.path.exists(venv_pip):
        log("INFO", "Upgrading LiteLLM and PyYAML inside .venv...")
        try:
            subprocess.run([venv_pip, "install", "--upgrade", "litellm[proxy]", "pyyaml"], check=True)
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
            
    # 3. Regenerate configs
    cmd_configure()
    log("SUCCESS", "Upgrade completed.")

def cmd_uninstall():
    print("\nWARNING: You are about to uninstall the OpenClaw Workstation package.")
    confirm = input("Are you sure you want to proceed? (yes/no): ").strip().lower()
    if confirm != "yes":
        log("INFO", "Uninstall cancelled.")
        return
        
    log("INFO", "Uninstalling packages...")
    
    # 1. Stop services
    cmd_stop()
    
    # 2. Remove venv directory
    venv_dir = os.path.join(ROOT_DIR, ".venv")
    if os.path.exists(venv_dir):
        log("INFO", f"Removing virtual environment directory at {venv_dir}...")
        try:
            shutil.rmtree(venv_dir)
            log("SUCCESS", "Virtual environment removed.")
        except Exception as e:
            log("ERROR", f"Could not remove .venv: {e}")
            
    # 3. Ask if they want to uninstall OpenClaw from npm
    uninstall_npm = input("Do you want to uninstall openclaw globally from npm? (yes/no): ").strip().lower()
    if uninstall_npm == "yes":
        tools = discover_tools()
        if "npm" in tools:
            log("INFO", "Removing openclaw via npm...")
            try:
                subprocess.run(["npm", "uninstall", "-g", "openclaw"], check=True)
                log("SUCCESS", "OpenClaw npm package uninstalled.")
            except Exception as e:
                log("ERROR", f"Failed to uninstall openclaw npm package: {e}")
                
    # 4. Ask if they want to remove generated configs and home directory configs
    remove_configs = input("Do you want to remove generated and local configurations (~/.openclaw)? (yes/no): ").strip().lower()
    if remove_configs == "yes":
        # remove generated dir
        if os.path.exists(GENERATED_DIR):
            shutil.rmtree(GENERATED_DIR)
        claw_home = os.path.join(get_user_home(), ".openclaw")
        if os.path.exists(claw_home):
            shutil.rmtree(claw_home)
        log("SUCCESS", "Configuration files removed.")
        
    log("SUCCESS", "Uninstall complete.")

# --- CLI Router ---

def main():
    parser = argparse.ArgumentParser(description="OpenClaw Workstation Manager CLI")
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
