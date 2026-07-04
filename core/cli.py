# core/cli.py
# CLI entry point and cross-cutting lifecycle commands for AIRM.

import argparse
import json
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
    # Historic GOOGLE_API_KEY→GEMINI_API_KEY rename now lives in the migration
    # framework (core/migrations.py, v1) and runs automatically at startup.
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
            "secrets": {"cloud_provider": "none", "vault_mount": "secret",
                        "azure_vault_name": "", "aws_region": ""},
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

def cmd_repair(interactive: bool = True) -> None:
    """Run self-healing checks: port scavenging, config repair, cache cleanup,
    and inventory-driven dependency remediation."""
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

    # 3. Dependency remediation (interactive=False plans without installing)
    from .repair import repair_dependencies
    repair_dependencies(interactive=interactive)

    log("SUCCESS", "Self-healing checks completed.")


def cmd_inventory() -> None:
    """Generate the enterprise dependency inventory (JSON report + console summary)."""
    from . import discovery

    log("INFO", "Scanning system for runtimes, SDKs, drivers, and platform features...")
    inventory = discovery.discover_dependency_inventory()

    for item in inventory["items"]:
        level = "SUCCESS" if item["status"] == "present" else "WARNING"
        version = f" v{item['version']}" if item["version"] else ""
        log(level, f"  {item['name']}: {item['status'].upper()}{version}")

    out_path = os.path.join(GENERATED_DIR, "dependency-inventory.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2)

    summary = inventory["summary"]
    log("SUCCESS", f"Dependency inventory written to {out_path} "
                   f"({summary['present']} present, {summary['missing']} missing).")


def cmd_secret(action: str, name: str = "") -> None:
    """Manage secrets in the OS credential store: list, set (also rotate), delete."""
    from . import secretstore
    from .config import _validate_env_var_name

    if action == "list":
        providers = load_yaml(PROVIDERS_PATH)
        env_vars = sorted({p.get("env_var") for p in providers.values()
                           if isinstance(p, dict) and p.get("env_var")})
        for var in env_vars:
            # get_windows_env also promotes any legacy plaintext copy it finds
            from .config import get_windows_env
            present = bool(get_windows_env(var))
            source = secretstore.describe_secret(var) if present else "not set"
            log("SUCCESS" if present else "WARNING", f"  {var}: {source}")
        return

    if action in ("set", "rotate"):
        if not name or not _validate_env_var_name(name):
            log("ERROR", "Usage: secret set <ENV_VAR_NAME>")
            return
        import getpass
        value = getpass.getpass(f"Value for {name} (input hidden): ").strip()
        if not value:
            log("INFO", "Empty value — nothing stored.")
            return
        from .config import set_windows_env
        if set_windows_env(name, value):
            log("SUCCESS", f"Secret {name} stored securely.")
        return

    if action == "delete":
        if not name:
            log("ERROR", "Usage: secret delete <ENV_VAR_NAME>")
            return
        if secretstore.delete_secret(name):
            log("SUCCESS", f"Secret {name} removed from the credential store.")
        else:
            log("WARNING", f"Secret {name} was not found in the credential store.")
        return

    log("ERROR", "Unknown secret action. Use one of: list, set, rotate, delete")


def cmd_user(action: str, name: str = "") -> None:
    """Manage local control-plane users (RBAC roles: admin, operator, viewer)."""
    from . import auth

    if action == "list":
        users = auth.list_users()
        if not users:
            log("INFO", "No local users defined. The dashboard session token remains the only login.")
        for username, info in sorted(users.items()):
            log("SUCCESS", f"  {username}: role={info['role']} created={info['created']}")
        return

    if action == "add":
        if not name:
            log("ERROR", "Usage: user add <username>")
            return
        import getpass
        password = getpass.getpass(f"Password for '{name}' (input hidden): ")
        if len(password) < 8:
            log("ERROR", "Password must be at least 8 characters.")
            return
        role = input(f"Role for '{name}' [{'/'.join(auth.ROLES)}] (default: operator): ").strip() or "operator"
        if auth.create_user(name, password, role):
            log("SUCCESS", f"User '{name}' saved with role '{role}'.")
        return

    if action == "remove":
        if name and auth.delete_user(name):
            log("SUCCESS", f"User '{name}' removed.")
        else:
            log("ERROR", f"User '{name or '<missing>'}' not found. Usage: user remove <username>")
        return

    log("ERROR", "Unknown user action. Use one of: list, add, remove")


def cmd_apikey(action: str, name: str = "") -> None:
    """Manage scoped API keys and service identities for the control plane."""
    from . import auth

    if action == "list":
        keys = auth.list_api_keys()
        if not keys:
            log("INFO", "No API keys issued.")
        for k in keys:
            scopes = ",".join(k["scopes"]) or "(full role)"
            log("SUCCESS", f"  [{k['id']}] {k['name']}: role={k['role']} scopes={scopes} "
                           f"type={k['type']} created={k['created']}")
        return

    if action == "create":
        if not name:
            log("ERROR", "Usage: apikey create <key-name>")
            return
        role = input(f"Role [{'/'.join(auth.ROLES)}] (default: operator): ").strip() or "operator"
        scopes_raw = input("Scopes, comma-separated subset of the role's permissions "
                           "(empty = full role): ").strip()
        scopes = [s.strip() for s in scopes_raw.split(",") if s.strip()] if scopes_raw else None
        service = input("Service identity? (yes/no, default no): ").strip().lower() == "yes"
        token = auth.create_api_key(name, role, scopes, service)
        if token:
            log("SUCCESS", f"API key '{name}' created. Shown ONCE — store it now:")
            print(f"\n  {token}\n")
        return

    if action == "revoke":
        if name and auth.revoke_api_key(name):
            log("SUCCESS", f"API key '{name}' revoked.")
        else:
            log("ERROR", f"API key '{name or '<missing>'}' not found. Usage: apikey revoke <name-or-id>")
        return

    log("ERROR", "Unknown apikey action. Use one of: list, create, revoke")


def cmd_migrate(action: str, name: str = "") -> None:
    """Version migration framework: apply pending, show status, or roll back."""
    from . import migrations

    if action in ("", "apply"):
        applied = migrations.migrate()
        if applied == 0:
            log("SUCCESS", f"Schema already current (v{migrations.current_version()}).")
        return

    if action == "status":
        info = migrations.status()
        log("INFO", f"Schema version: v{info['current_version']} (latest: v{info['latest_version']})")
        for p in info["pending"]:
            log("WARNING", f"  pending v{p['version']}: {p['description']}"
                           f"{'' if p['reversible'] else ' (irreversible)'}")
        for h in info["history"][-10:]:
            log("INFO", f"  {h['at']} {h['direction']} v{h['version']}: {h['description']}")
        return

    if action == "rollback":
        if not (name and name.isdigit()):
            log("ERROR", "Usage: migrate rollback <target-version>")
            return
        try:
            migrations.rollback(int(name))
        except migrations.MigrationError as e:
            log("ERROR", str(e))
        return

    log("ERROR", "Unknown migrate action. Use one of: apply, status, rollback <version>")


def cmd_history(action: str, name: str = "") -> None:
    """Configuration version history: list, diff, rollback, tag."""
    from . import confighistory

    if action == "list":
        entries = confighistory.history_list(name)
        if not entries:
            log("INFO", "No configuration history yet. Snapshots appear on the next config change.")
        for e in entries:
            tag_txt = f" tag={e['tag']}" if e.get("tag") else ""
            conflict_txt = " [external edit]" if e.get("conflict") else ""
            log("INFO", f"  [{e['id']}] {e['ts']} {e['file']}{tag_txt}{conflict_txt}")
        return

    if action in ("diff", "rollback", "tag"):
        if not (name and name.isdigit()):
            log("ERROR", f"Usage: history {action} <entry-id>   (see 'history list')")
            return
        entry_id = int(name)
        if action == "diff":
            print(confighistory.diff(entry_id) or "No differences against the current file.")
        elif action == "rollback":
            if confighistory.rollback(entry_id):
                cmd_configure()  # recompile blueprints from the restored config
        else:
            label = input("Tag label: ").strip()
            if label and confighistory.tag(entry_id, label):
                log("SUCCESS", f"Entry {entry_id} tagged '{label}'.")
        return

    log("ERROR", "Unknown history action. Use one of: list [file], diff <id>, rollback <id>, tag <id>")


def cmd_upgrade() -> None:
    """Upgrade Python and npm packages."""
    log("INFO", "Running package upgrade suite...")

    from . import discovery

    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]

    venv_pip = os.path.join(ROOT_DIR, VENV_DIR, "Scripts", "pip.exe")
    requirements = os.path.join(ROOT_DIR, "requirements.txt")
    if os.path.exists(venv_pip):
        log("INFO", "Upgrading LiteLLM and PyYAML inside .venv...")
        try:
            subprocess.run([venv_pip, "install", "--upgrade", "-r", requirements], check=True)
            log("SUCCESS", "LiteLLM upgraded in .venv.")
        except Exception as e:
            log("ERROR", f"Failed to upgrade python packages in .venv: {e}")
            # requirements.txt is fully pinned, so reinstalling it restores the
            # known-good versions — rollback for a partially applied upgrade.
            log("INFO", "Rolling back to pinned dependency versions...")
            try:
                subprocess.run([venv_pip, "install", "-r", requirements], check=True)
                log("SUCCESS", "Rolled back python packages to pinned versions.")
            except Exception as rb:
                log("ERROR", f"Rollback failed: {rb}. Run 'Manage.bat repair' to restore packages.")

    if "npm" in tools:
        log("INFO", "Upgrading OpenClaw globally via npm...")
        try:
            subprocess.run(["npm", "update", "-g", "openclaw"], check=True)
            log("SUCCESS", "OpenClaw package updated.")
        except Exception as e:
            log("ERROR", f"Failed to upgrade OpenClaw via npm: {e}")

    from .repair import upgrade_managed_runtimes
    upgrade_managed_runtimes()

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
        "diagnose", "inventory", "repair", "backup", "restore", "upgrade", "uninstall",
        "service", "secret", "user", "apikey", "migrate", "history",
    ], help="Command to run")
    parser.add_argument("action", nargs="?", default=None,
                        help="Sub-action, e.g. 'service install' or 'secret list'")
    parser.add_argument("name", nargs="?", default=None,
                        help="Target name for sub-actions, e.g. 'secret set GEMINI_API_KEY'")

    args = parser.parse_args()

    # Compatibility gate + auto-migration before any command touches state.
    # 'migrate' itself is exempt so status/rollback work on any schema.
    from . import migrations
    if args.command != "migrate":
        try:
            migrations.ensure_current()
        except migrations.MigrationError as e:
            log("ERROR", str(e))
            sys.exit(1)
    else:
        cmd_migrate(args.action or "apply", args.name or "")
        return

    if args.command == "service":
        from .service import cmd_service
        cmd_service(args.action or "status")
        return
    if args.command == "secret":
        cmd_secret(args.action or "list", args.name or "")
        return
    if args.command == "user":
        cmd_user(args.action or "list", args.name or "")
        return
    if args.command == "apikey":
        cmd_apikey(args.action or "list", args.name or "")
        return
    if args.command == "history":
        cmd_history(args.action or "list", args.name or "")
        return

    commands = {
        "install": cmd_install,
        "configure": cmd_configure,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "watch": cmd_watch,
        "diagnose": cmd_diagnose,
        "inventory": cmd_inventory,
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
