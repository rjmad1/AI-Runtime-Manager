# core/cli.py
# CLI entry point and cross-cutting lifecycle commands for AIRM.

import argparse
import os
import shutil
import subprocess
import sys

from .backup import cmd_backup, cmd_restore
from .config import (
    GENERATED_DIR,
    MODELS_PATH,
    PROVIDERS_PATH,
    ROOT_DIR,
    SETTINGS_PATH,
    cmd_configure,
    ensure_runtime_dirs,
    load_yaml,
    log,
    save_yaml,
)
from .diagnostics import LiteLLMOfflineError, cmd_diagnose
from .process import cmd_start, cmd_status, cmd_stop, cmd_watch, scavenge_ports

LLAMA_SAMBANOVA = "llama-3.3-70b-sambanova"
LLAMA_GROQ = "llama-3.3-70b-groq"
LLAMA_CEREBRAS = "llama-3.1-70b-cerebras"
VENV_DIR = ".venv"


def cmd_install() -> None:
    """Launch the guided visual setup assistant."""
    log("INFO", "Starting guided visual setup assistant...")
    from .config import get_windows_env, set_windows_env

    # Migrate old GOOGLE_API_KEY to GEMINI_API_KEY
    gemini_key = get_windows_env("GEMINI_API_KEY")
    if not gemini_key:
        google_key = get_windows_env("GOOGLE_API_KEY")
        if google_key:
            log("INFO", "Migrating GOOGLE_API_KEY to GEMINI_API_KEY...")
            set_windows_env("GEMINI_API_KEY", google_key)

    try:
        log("INFO", "Opening Web Control Center...")
        subprocess.run([sys.executable, "-m", "core.prompt_server"], cwd=ROOT_DIR)
    except Exception as e:
        log("ERROR", f"Failed to launch installation assistant: {e}")


def _repair_config() -> None:
    """Repair configuration files."""
    if not os.path.exists(SETTINGS_PATH) or os.path.getsize(SETTINGS_PATH) == 0:
        log("WARNING", "settings.yaml was corrupted or missing. Restoring default template...")
        default_settings = {
            "litellm": {
                "host": "127.0.0.1", "port": 4000, "api_key": "",
                "set_verbose": False, "drop_params": True,
                "routing_strategy": "latency-based-routing",
                "num_retries": 3, "request_timeout": 30,
            },
            "openclaw": {"host": "127.0.0.1", "port": 18789, "config_dir": ""},
            "ollama": {"enabled": True, "api_base": "http://127.0.0.1:11434", "autostart": True},
            "lifecycle": {"log_level": "INFO", "backup_dir": "backups", "auto_cleanup_ports": True},
        }
        save_yaml(default_settings, SETTINGS_PATH)

    if not os.path.exists(PROVIDERS_PATH) or os.path.getsize(PROVIDERS_PATH) == 0:
        log("WARNING", "providers.yaml was corrupted or missing. Restoring default template...")
        default_providers = {
            "gemini": {"enabled": True, "env_var": "GEMINI_API_KEY", "info": "Free tier available at Google AI Studio"},
            "groq": {"enabled": True, "env_var": "GROQ_API_KEY", "info": "Free tier available at Groq Console"},
            "sambanova": {"enabled": True, "env_var": "SAMBANOVA_API_KEY", "info": "Free API key available at SambaNova Cloud"},
            "cerebras": {"enabled": True, "env_var": "CEREBRAS_API_KEY", "info": "Free API key available at Cerebras Console"},
            "openrouter": {"enabled": True, "env_var": "OPENROUTER_API_KEY", "info": "Sign up at OpenRouter"},
        }
        save_yaml(default_providers, PROVIDERS_PATH)

    if not os.path.exists(MODELS_PATH) or os.path.getsize(MODELS_PATH) == 0:
        log("WARNING", "models.yaml was corrupted or missing. Restoring default template...")
        default_models = {"models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "gemini", "litellm_model": "gemini/gemini-2.5-flash", "context_window": 1048576, "max_tokens": 8192, "fallbacks": [LLAMA_SAMBANOVA, LLAMA_GROQ]},
            {"id": LLAMA_GROQ, "name": "Llama 3.3 70B (Groq)", "provider": "groq", "litellm_model": "groq/llama-3.3-70b-versatile", "context_window": 4096, "max_tokens": 4096, "fallbacks": [LLAMA_SAMBANOVA, LLAMA_CEREBRAS]},
            {"id": LLAMA_SAMBANOVA, "name": "Llama 3.3 70B (SambaNova)", "provider": "sambanova", "litellm_model": "sambanova/Meta-Llama-3.3-70B-Instruct", "context_window": 4096, "max_tokens": 4096, "fallbacks": [LLAMA_GROQ, LLAMA_CEREBRAS]},
            {"id": LLAMA_CEREBRAS, "name": "Llama 3.1 70B (Cerebras)", "provider": "cerebras", "litellm_model": "cerebras/llama3.1-70b", "context_window": 8192, "max_tokens": 4096, "fallbacks": [LLAMA_SAMBANOVA, LLAMA_GROQ]},
        ]}
        save_yaml(default_models, MODELS_PATH)

    try:
        cmd_configure()
        log("SUCCESS", "YAML schemas parsed and compiled successfully.")
    except Exception as e:
        log("ERROR", f"Failed to rebuild configuration blueprints: {e}")

def _repair_cache_and_packages() -> None:
    """Repair cache and package integrity."""
    # 3. Cache cleanup
    litellm_cache = os.path.join(os.path.expanduser("~"), ".cache", "litellm")
    if os.path.exists(litellm_cache):
        log("INFO", f"Cleaning LiteLLM cache at {litellm_cache}...")
        try:
            shutil.rmtree(litellm_cache)
            log("SUCCESS", "LiteLLM cache cleaned.")
        except Exception as e:
            log("WARNING", f"Could not clean LiteLLM cache: {e}")

    # 4. Package integrity
    try:
        import litellm  # noqa: F401
        log("SUCCESS", "Python package dependencies verified successfully.")
    except ImportError:
        log("WARNING", "LiteLLM python package is missing. Attempting silent reinstall...")
        venv_pip = os.path.join(ROOT_DIR, VENV_DIR, "Scripts", "pip.exe")
        if os.path.exists(venv_pip):
            try:
                subprocess.run(
                    [venv_pip, "install", "-r", os.path.join(ROOT_DIR, "requirements.txt")],
                    check=True, capture_output=True,
                )
                log("SUCCESS", "LiteLLM package reinstalled successfully.")
            except Exception as e:
                log("ERROR", f"Failed to run package repair reinstall: {e}")

def cmd_repair() -> None:
    """Run self-healing checks: port scavenging, config repair, cache cleanup."""
    log("INFO", "Initiating system self-healing check...")
    settings = load_yaml(SETTINGS_PATH)
    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    openclaw_port: int = settings.get("openclaw", {}).get("port", 18789)

    # 1. Port cleanup
    log("INFO", "Port Auditing: release lock on workstation ports...")
    scavenge_ports([litellm_port, openclaw_port])

    # 2. Configuration repair
    log("INFO", "Configuration Auditing: checking configuration blueprint schemas...")
    _repair_config()
    _repair_cache_and_packages()

    log("SUCCESS", "Self-healing checks completed.")


def cmd_upgrade() -> None:
    """Upgrade Python and npm packages."""
    log("INFO", "Running package upgrade suite...")

    from . import discovery

    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]

    venv_pip = os.path.join(ROOT_DIR, VENV_DIR, "Scripts", "pip.exe")
    if os.path.exists(venv_pip):
        log("INFO", "Upgrading LiteLLM and PyYAML inside .venv...")
        try:
            subprocess.run(
                [venv_pip, "install", "--upgrade", "-r", os.path.join(ROOT_DIR, "requirements.txt")],
                check=True,
            )
            log("SUCCESS", "LiteLLM upgraded in .venv.")
        except Exception as e:
            log("ERROR", f"Failed to upgrade python packages in .venv: {e}")

    if "npm" in tools:
        log("INFO", "Upgrading OpenClaw globally via npm...")
        try:
            subprocess.run(["npm", "update", "-g", "openclaw"], check=True)
            log("SUCCESS", "OpenClaw package updated.")
        except Exception as e:
            log("ERROR", f"Failed to upgrade OpenClaw via npm: {e}")

    cmd_configure()
    log("SUCCESS", "Upgrade completed.")


def _uninstall_packages() -> None:
    """Uninstall the AIRM workspace packages."""
    log("INFO", "Uninstalling packages...")
    cmd_stop()

    venv_dir = os.path.join(ROOT_DIR, VENV_DIR)
    if os.path.exists(venv_dir):
        log("INFO", f"Removing virtual environment directory at {venv_dir}...")
        try:
            shutil.rmtree(venv_dir)
            log("SUCCESS", "Virtual environment removed.")
        except Exception as e:
            log("ERROR", f"Could not remove .venv: {e}")

    uninstall_npm = input("Do you want to uninstall openclaw globally from npm? (yes/no): ").strip().lower()
    if uninstall_npm == "yes":
        from . import discovery

        sys_details = discovery.run_all_discovery(SETTINGS_PATH)
        tools = sys_details["tools"]
        if "npm" in tools:
            log("INFO", "Removing openclaw via npm...")
            try:
                subprocess.run(["npm", "uninstall", "-g", "openclaw"], check=True)
                log("SUCCESS", "OpenClaw npm package uninstalled.")
            except Exception as e:
                log("ERROR", f"Failed to uninstall openclaw npm package: {e}")

def _uninstall_configs() -> None:
    """Remove configuration directories."""
    remove_configs = input("Do you want to remove generated and local configurations (~/.openclaw)? (yes/no): ").strip().lower()
    if remove_configs == "yes":
        if os.path.exists(GENERATED_DIR):
            shutil.rmtree(GENERATED_DIR)
        claw_home = os.path.join(os.path.expanduser("~"), ".openclaw")
        if os.path.exists(claw_home):
            shutil.rmtree(claw_home)
        log("SUCCESS", "Configuration files removed.")

def cmd_uninstall() -> None:
    """Uninstall the AIRM workspace and optionally clean all artifacts."""
    print("\nWARNING: You are about to uninstall the OpenClaw Workstation package.")
    confirm = input("Are you sure you want to proceed? (yes/no): ").strip().lower()
    if confirm != "yes":
        log("INFO", "Uninstall cancelled.")
        return

    _uninstall_packages()
    _uninstall_configs()

    log("SUCCESS", "Uninstall complete.")


def main() -> None:
    """CLI entry point for the AIRM lifecycle manager."""
    ensure_runtime_dirs()
    parser = argparse.ArgumentParser(description="OpenClaw Workstation Lifecycle Manager CLI")
    parser.add_argument("command", choices=[
        "install", "configure", "start", "stop", "status", "watch",
        "diagnose", "repair", "backup", "restore", "upgrade", "uninstall",
    ], help="Command to run")

    args = parser.parse_args()

    commands = {
        "install": cmd_install,
        "configure": cmd_configure,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "watch": cmd_watch,
        "diagnose": cmd_diagnose,
        "repair": cmd_repair,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "upgrade": cmd_upgrade,
        "uninstall": cmd_uninstall,
    }
    try:
        commands[args.command]()
    except LiteLLMOfflineError as e:
        log("ERROR", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
