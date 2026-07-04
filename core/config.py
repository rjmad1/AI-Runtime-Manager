# core/config.py
# Configuration management, constants, logging, and YAML utilities for AIRM.

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
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

# Deferred: directories are NOT created at import time.
# Call ensure_runtime_dirs() from CLI entry points and server startup.

LOG_FILE: str = os.path.join(LOGS_DIR, "installer.log")


def ensure_runtime_dirs() -> None:
    """Create CONFIG_DIR, GENERATED_DIR, and LOGS_DIR if they do not exist.

    This must be called explicitly from CLI entry points and server startup
    before any file I/O occurs.  Importing this module does NOT create
    directories as a side effect.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(GENERATED_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)


_runtime_dirs_ensured: bool = False

_LEVEL_COLORS: Dict[str, str] = {
    "INFO": "\033[36m",
    "SUCCESS": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
}

# --- Security Constants ---
# API key patterns to mask in logs
_API_KEY_PATTERNS = [
    r'(sk-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+',
    r'(nvapi-[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+',
    r'(gsk_[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+',
    r'(rn_)[a-zA-Z0-9_-]+',
    r'(hf_[a-zA-Z0-9]{12})[a-zA-Z0-9_-]+',
]

# Allowed directories for file operations
_ALLOWED_DIRS = [CONFIG_DIR, GENERATED_DIR, LOGS_DIR, ROOT_DIR]


def _is_safe_path(path: str, base_dir: str) -> bool:
    """Check if path is within allowed directories to prevent path traversal."""
    try:
        base = os.path.abspath(base_dir)
        target = os.path.abspath(path)
        return target.startswith(base)
    except (ValueError, OSError):
        return False


def _validate_provider_name(provider: str) -> bool:
    """Validate provider name to prevent injection attacks."""
    if not provider or len(provider) > 50:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', provider))


def _validate_model_id(model_id: str) -> bool:
    """Validate model ID to prevent injection attacks."""
    if not model_id or len(model_id) > 100:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_/-]+$', model_id))


def _validate_env_var_name(name: str) -> bool:
    """Validate environment variable name."""
    if not name or len(name) > 100:
        return False
    return bool(re.match(r'^[A-Z][A-Z0-9_]*$', name))


def _mask_secrets(message: str) -> str:
    """Mask all API key patterns in log messages."""
    clean_msg = message
    for pattern in _API_KEY_PATTERNS:
        clean_msg = re.sub(pattern, r'\1...', clean_msg)
    return clean_msg


def log(level: str, message: str) -> None:
    """Log a message with color, timestamp, and secret masking."""
    global _runtime_dirs_ensured
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_msg = _mask_secrets(message)

    color = _LEVEL_COLORS.get(level, "")
    reset = "\033[0m"
    print(f"{color}[{level}] {clean_msg}{reset}")
    sys.stdout.flush()

    # Ensure LOGS_DIR exists on first log write so the caller does not need
    # to call ensure_runtime_dirs() before the first log statement.
    if not _runtime_dirs_ensured:
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            _runtime_dirs_ensured = True
        except Exception:
            pass

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
        log("ERROR", "PyYAML is not installed. Run 'Manage.bat repair' to restore dependencies.")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log("WARNING", f"Failed to parse YAML file {path}: {e}")
        return {}


def save_yaml(data: Dict[str, Any], path: str) -> None:
    """Save data to a YAML file. Requires PyYAML.

    Versioned configuration files (settings/providers/models) are snapshotted
    into the config history before being overwritten (core/confighistory)."""
    if not HAS_YAML:
        log("ERROR", "PyYAML is not installed. Cannot write configuration.")
        return
    from . import confighistory  # lazy: keep module dependency unidirectional
    content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    confighistory.before_save(path, new_content=content)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    confighistory.after_save(path)


# --- Windows persistent user variable helpers ---

def _legacy_env_get(name: str) -> Optional[str]:
    """Legacy plaintext lookup: Windows user registry / ~/.airm_env."""
    if platform.system() == "Windows":
        try:
            # Escape single quotes for PowerShell
            safe_name = name.replace("'", "''")
            cmd = f"[System.Environment]::GetEnvironmentVariable('{safe_name}', 'User')"
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, check=True,
            )
            val = res.stdout.strip()
            if val:
                return val
        except subprocess.CalledProcessError as e:
            log("WARNING", f"Failed to get env variable {name}: {e}")
        except Exception as e:
            log("WARNING", f"Unexpected error getting env variable {name}: {e}")
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
            except Exception as e:
                log("WARNING", f"Failed to read env file: {e}")
    return None


def get_windows_env(name: str) -> Optional[str]:
    """Resolve a secret/environment value.

    Resolution order: OS credential store (via core/secretstore) → legacy
    plaintext locations (registry / ~/.airm_env, transparently promoted into
    the credential store when found) → process environment."""
    if not _validate_env_var_name(name):
        log("ERROR", f"Invalid environment variable name: {name}")
        return None

    from . import secretstore  # lazy: keep module dependency unidirectional
    value = secretstore.get_secret(name)
    if value:
        return value

    legacy = _legacy_env_get(name)
    if legacy:
        secretstore.migrate_legacy(name, legacy)
        return legacy
    return os.environ.get(name)


def _legacy_env_set(name: str, value: str) -> bool:
    """Legacy plaintext write: Windows user registry / ~/.airm_env.

    Only used as a fallback when no OS credential store is available."""
    if platform.system() == "Windows":
        try:
            # Escape single quotes for PowerShell to prevent injection
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
        except subprocess.CalledProcessError as e:
            log("ERROR", f"Failed to save env variable {name}: {e}")
            return False
        except Exception as e:
            log("ERROR", f"Unexpected error saving env variable {name}: {e}")
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


def set_windows_env(name: str, value: str) -> bool:
    """Store a secret/environment value.

    Writes to the OS credential store (encrypted at rest); falls back to the
    legacy plaintext locations only when no store is available. The process
    environment is always updated so spawned daemons inherit the value."""
    if not _validate_env_var_name(name):
        log("ERROR", f"Invalid environment variable name: {name}")
        return False

    from . import secretstore  # lazy: keep module dependency unidirectional
    if secretstore.set_secret(name, value):
        os.environ[name] = value
        return True

    log("WARNING", f"No OS credential store available. Storing {name} in the legacy "
                   "plaintext environment location.")
    return _legacy_env_set(name, value)


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

    # Validate path to prevent traversal attacks
    if not _is_safe_path(config_dir, os.path.expanduser("~")):
        log("ERROR", f"Invalid config_dir path: {config_dir}")
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
        # Rotate any token that was not generated by secrets.token_hex(24).
        # A valid token is exactly 48 lowercase hex characters (24 bytes × 2).
        # Anything shorter, longer, or missing is treated as an insecure bootstrap
        # state and replaced — this covers historic default tokens without
        # embedding any known-bad literal value in source.
        current_token = auth.get("token", "")
        _HEX_RE = re.compile(r'^[0-9a-f]{48}$')
        if not _HEX_RE.match(current_token):
            log("WARNING", "Insecure or legacy auth token detected. Rotating to a new secure token...")
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
    ensure_runtime_dirs()
    log("INFO", "Compiling configuration blueprints...")

    # Lazy import to keep module dependency unidirectional
    from . import discovery

    settings = load_yaml(SETTINGS_PATH)
    providers = load_yaml(PROVIDERS_PATH)
    models_reg = load_yaml(MODELS_PATH)

    if not settings or not providers or not models_reg:
        log("ERROR", "YAML settings files are missing or corrupted. Run 'Manage.bat repair' to restore them.")
        raise RuntimeError("YAML settings files are missing or corrupted.")

    # Generate LiteLLM API key on first configure (empty string = not yet set)
    litellm_key = settings.get("litellm", {}).get("api_key", "")
    if not litellm_key:
        new_key = f"sk-airm-{secrets.token_hex(16)}"
        log("INFO", "Generating unique LiteLLM API key...")
        settings.setdefault("litellm", {})["api_key"] = new_key
        save_yaml(settings, SETTINGS_PATH)
        litellm_key = new_key

    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]

    ollama_models = _setup_ollama(settings, tools, discovery)
    _compile_litellm_config(settings, providers, models_reg, ollama_models)
    openclaw_cfg, openclaw_models = _compile_openclaw_config(settings, providers, models_reg, ollama_models)
    _sync_active_config(settings, openclaw_cfg, openclaw_models)
