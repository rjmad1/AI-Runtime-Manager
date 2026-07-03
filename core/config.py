# core/config.py
# Configuration management, constants, logging, and YAML utilities for AIRM.

import os
import sys
import json
import re
import subprocess
import shutil
import secrets
import time
import platform
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

# Safe YAML Loader
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# --- Constants & Paths ---
CORE_DIR: str = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR: str = os.path.dirname(CORE_DIR)
CONFIG_DIR: str = os.path.join(ROOT_DIR, "OpenClawManager")
GENERATED_DIR: str = os.path.join(ROOT_DIR, "generated")
LOGS_DIR: str = os.path.join(ROOT_DIR, "logs")

SETTINGS_PATH: str = os.path.join(CONFIG_DIR, "settings.yaml")
PROVIDERS_PATH: str = os.path.join(CONFIG_DIR, "providers.yaml")
MODELS_PATH: str = os.path.join(CONFIG_DIR, "models.yaml")

LITELLM_CONFIG_PATH: str = os.path.join(GENERATED_DIR, "config.yaml")
OPENCLAW_CONFIG_PATH: str = os.path.join(GENERATED_DIR, "openclaw.json")
SERVICES_STATE_PATH: str = os.path.join(GENERATED_DIR, "services.json")

# Ensure folders exist
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

LOG_FILE: str = os.path.join(LOGS_DIR, "installer.log")

_LEVEL_COLORS: Dict[str, str] = {
    "INFO": "\033[36m",
    "SUCCESS": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
}


def log(level: str, message: str) -> None:
    """Log a message with color, timestamp, and secret masking."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_msg = re.sub(r'(sk-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+', r'\1...', message)
    clean_msg = re.sub(r'(nvapi-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+', r'\1...', clean_msg)

    color = _LEVEL_COLORS.get(level, "")
    reset = "\033[0m"
    print(f"{color}[{level}] {clean_msg}{reset}")
    sys.stdout.flush()

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{level}] {clean_msg}\n")
    except Exception:
        pass


def load_yaml(path: str) -> Dict[str, Any]:
    """Load a YAML file safely, returning empty dict on failure."""
    if not os.path.exists(path):
        return {}
    if not HAS_YAML:
        log("ERROR", "PyYAML is not installed. Run Repair.bat to restore dependencies.")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log("WARNING", f"Failed to parse YAML file {path}: {e}")
        return {}


def save_yaml(data: Dict[str, Any], path: str) -> None:
    """Save data to a YAML file. Requires PyYAML."""
    if not HAS_YAML:
        log("ERROR", "PyYAML is not installed. Cannot write configuration.")
        return
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


# --- Windows persistent user variable helpers ---

def get_windows_env(name: str) -> Optional[str]:
    """Retrieve an environment variable (cross-platform)."""
    if platform.system() == "Windows":
        try:
            cmd = f"[System.Environment]::GetEnvironmentVariable('{name}', 'User')"
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, check=True,
            )
            val = res.stdout.strip()
            if val:
                return val
        except Exception:
            pass
    else:
        env_file = os.path.expanduser("~/.airm_env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith(f"export {name}="):
                            # Extract value inside quotes if present
                            val = line.split("=", 1)[1].strip()
                            if val.startswith('"') and val.endswith('"'):
                                return val[1:-1]
                            if val.startswith("'") and val.endswith("'"):
                                return val[1:-1]
                            return val
            except Exception:
                pass
    return os.environ.get(name)


def set_windows_env(name: str, value: str) -> bool:
    """Set an environment variable (cross-platform)."""
    if platform.system() == "Windows":
        try:
            safe_name = name.replace("'", "''")
            safe_value = value.replace("'", "''")
            cmd = (
                f"[System.Environment]::SetEnvironmentVariable("
                f"'{safe_name}', '{safe_value}', 'User')"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, check=True,
            )
            os.environ[name] = value
            return True
        except Exception as e:
            log("ERROR", f"Failed to save env variable {name}: {e}")
            return False
    else:
        env_file = os.path.expanduser("~/.airm_env")
        try:
            lines = []
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            
            new_lines = []
            found = False
            for line in lines:
                if line.startswith(f"export {name}="):
                    new_lines.append(f'export {name}="{value}"\n')
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f'export {name}="{value}"\n')
                
            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            os.environ[name] = value
            return True
        except Exception as e:
            log("ERROR", f"Failed to save env variable {name}: {e}")
            return False


# --- Configuration Compilation Helpers ---

def _setup_ollama(settings: Dict[str, Any], tools: Dict[str, Any], discovery: Any) -> List[Dict[str, Any]]:
    ollama_enabled: bool = settings.get("ollama", {}).get("enabled", True)
    ollama_api: str = settings.get("ollama", {}).get("api_base", "http://127.0.0.1:11434")
    ollama_autostart: bool = settings.get("ollama", {}).get("autostart", True)

    ollama_models: List[Dict[str, Any]] = []
    if ollama_enabled:
        ollama_models = discovery.get_ollama_models(ollama_api)
        if not ollama_models and ollama_autostart and "ollama" in tools:
            log("INFO", "Starting Ollama service...")
            try:
                subprocess.Popen(
                    [tools["ollama"], "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                for _ in range(5):
                    time.sleep(1)
                    ollama_models = discovery.get_ollama_models(ollama_api)
                    if ollama_models:
                        log("SUCCESS", "Ollama connected successfully.")
                        break
            except Exception as e:
                log("WARNING", f"Could not serve Ollama: {e}")
    return ollama_models

def _compile_litellm_config(settings: Dict[str, Any], providers: Dict[str, Any], models_reg: Dict[str, Any], ollama_models: List[Dict[str, Any]]) -> None:
    litellm_models: List[Dict[str, Any]] = []
    active_model_ids: Set[str] = set()

    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        if isinstance(p_cfg, dict) and p_cfg.get("enabled", False):
            env_var = p_cfg.get("env_var")
            key_val = get_windows_env(env_var)
            if key_val:
                litellm_models.append({
                    "model_name": m.get("id"),
                    "litellm_params": {
                        "model": m.get("litellm_model"),
                        "api_key": f"os.environ/{env_var}",
                    },
                })
                active_model_ids.add(m.get("id"))

    ollama_api: str = settings.get("ollama", {}).get("api_base", "http://127.0.0.1:11434")
    for om in ollama_models:
        om_name = om.get("name")
        ollama_id = f"ollama/{om_name}"
        litellm_models.append({
            "model_name": ollama_id,
            "litellm_params": {"model": ollama_id, "api_base": ollama_api},
        })
        active_model_ids.add(ollama_id)

    # Compute fallbacks
    active_fallbacks: Dict[str, List[str]] = {}
    for m in models_reg.get("models", []):
        mid = m.get("id")
        if mid in active_model_ids and m.get("fallbacks"):
            fbs = [fb for fb in m.get("fallbacks") if fb in active_model_ids]
            if fbs:
                active_fallbacks[mid] = fbs

    litellm_config: Dict[str, Any] = {
        "model_list": litellm_models,
        "litellm_settings": {
            "drop_params": settings.get("litellm", {}).get("drop_params", True),
            "set_verbose": settings.get("litellm", {}).get("set_verbose", False),
        },
        "router_settings": {
            "routing_strategy": settings.get("litellm", {}).get("routing_strategy", "latency-based-routing"),
            "num_retries": settings.get("litellm", {}).get("num_retries", 3),
            "request_timeout": settings.get("litellm", {}).get("request_timeout", 30),
            "fallbacks": [{k: v} for k, v in active_fallbacks.items()],
        },
    }
    save_yaml(litellm_config, LITELLM_CONFIG_PATH)
    log("SUCCESS", f"LiteLLM config compiled: {LITELLM_CONFIG_PATH}")

def _compile_openclaw_config(settings: Dict[str, Any], providers: Dict[str, Any], models_reg: Dict[str, Any], ollama_models: List[Dict[str, Any]]) -> tuple:
    openclaw_models: List[Dict[str, Any]] = []
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        if isinstance(p_cfg, dict) and p_cfg.get("enabled", False) and get_windows_env(p_cfg.get("env_var")):
            openclaw_models.append({
                "id": m.get("id"),
                "name": m.get("name"),
                "contextWindow": m.get("context_window", 4096),
                "maxTokens": m.get("max_tokens", 4096),
            })

    for om in ollama_models:
        om_name = om.get("name")
        openclaw_models.append({
            "id": f"ollama/{om_name}",
            "name": f"{om_name} (Ollama)",
            "contextWindow": 4096,
            "maxTokens": 4096,
        })

    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    openclaw_cfg: Dict[str, Any] = {
        "models": {
            "providers": {
                "litellm": {
                    "baseUrl": f"http://localhost:{litellm_port}",
                    "apiKey": "${LITELLM_API_KEY}",
                    "api": "openai-completions",
                    "models": openclaw_models,
                }
            }
        }
    }

    with open(OPENCLAW_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(openclaw_cfg, f, indent=2)
    log("SUCCESS", f"OpenClaw gateway config compiled: {OPENCLAW_CONFIG_PATH}")
    return openclaw_cfg, openclaw_models

def _sync_active_config(settings: Dict[str, Any], openclaw_cfg: Dict[str, Any], openclaw_models: List[Dict[str, Any]]) -> None:
    config_dir = settings.get("openclaw", {}).get("config_dir")
    if not config_dir:
        config_dir = os.path.join(os.path.expanduser("~"), ".openclaw")
    os.makedirs(config_dir, exist_ok=True)

    active_claw_path = os.path.join(config_dir, "openclaw.json")
    existing_data: Dict[str, Any] = {}

    if os.path.exists(active_claw_path):
        try:
            with open(active_claw_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            shutil.copy2(active_claw_path, active_claw_path + ".bak")
        except Exception as e:
            log("WARNING", f"Corrupted active config: {e}. Re-initializing.")

    if "gateway" not in existing_data:
        existing_data["gateway"] = {
            "auth": {"mode": "token", "token": secrets.token_hex(24)},
            "bind": "loopback",
            "mode": "local",
            "port": settings.get("openclaw", {}).get("port", 18789),
        }
    else:
        auth = existing_data["gateway"].get("auth", {})
        if auth.get("token") == "7d07bed5a8d8621d4dab6bec133d7297e58f915902437007":
            log("WARNING", "Upgrading default static token to dynamic secure token...")
            existing_data["gateway"].setdefault("auth", {})["token"] = secrets.token_hex(24)

    existing_data.setdefault("models", {}).setdefault("providers", {})
    existing_data["models"]["providers"]["litellm"] = openclaw_cfg["models"]["providers"]["litellm"]

    existing_data.setdefault("agents", {}).setdefault("defaults", {})
    primary = "litellm/gemini-2.5-flash"
    fallbacks: List[str] = []
    active_ids = [m["id"] for m in openclaw_models]
    if active_ids:
        primary = f"litellm/{active_ids[0]}"
        fallbacks = [f"litellm/{aid}" for aid in active_ids[1:]]

    existing_data["agents"]["defaults"]["model"] = {"primary": primary, "fallbacks": fallbacks}
    existing_data["agents"]["defaults"]["models"] = {f"litellm/{aid}": {} for aid in active_ids}
    existing_data["agents"]["defaults"].setdefault("workspace", os.path.join(config_dir, "workspace"))

    try:
        with open(active_claw_path, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2)
        log("SUCCESS", f"Successfully synced active configuration: {active_claw_path}")
    except Exception as e:
        log("ERROR", f"Failed to sync openclaw.json: {e}")
        if os.path.exists(active_claw_path + ".bak"):
            shutil.copy2(active_claw_path + ".bak", active_claw_path)
            log("INFO", "Rolled back configuration from backup.")

def cmd_configure() -> None:
    """Compile LiteLLM and OpenClaw configuration blueprints from YAML sources."""
    log("INFO", "Compiling configuration blueprints...")

    # Lazy import to keep module dependency unidirectional
    try:
        import discovery
    except ImportError:
        sys.path.append(CORE_DIR)
        import discovery

    settings = load_yaml(SETTINGS_PATH)
    providers = load_yaml(PROVIDERS_PATH)
    models_reg = load_yaml(MODELS_PATH)

    if not settings or not providers or not models_reg:
        log("ERROR", "YAML settings files are missing or corrupted. Run 'Repair.bat' to restore them.")
        raise RuntimeError("YAML settings files are missing or corrupted.")

    # Rotate default LiteLLM API key on first configure
    litellm_key = settings.get("litellm", {}).get("api_key", "sk-litellm-key")
    if litellm_key == "sk-litellm-key":
        new_key = f"sk-airm-{secrets.token_hex(16)}"
        log("INFO", "Generating unique LiteLLM API key (replacing insecure default)...")
        settings.setdefault("litellm", {})["api_key"] = new_key
        save_yaml(settings, SETTINGS_PATH)
        litellm_key = new_key

    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]

    ollama_models = _setup_ollama(settings, tools, discovery)
    _compile_litellm_config(settings, providers, models_reg, ollama_models)
    openclaw_cfg, openclaw_models = _compile_openclaw_config(settings, providers, models_reg, ollama_models)
    _sync_active_config(settings, openclaw_cfg, openclaw_models)
