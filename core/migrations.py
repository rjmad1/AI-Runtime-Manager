# core/migrations.py
# Version migration framework for AIRM.
# Ordered, versioned migrations over configuration, runtime artifacts, and
# caches, with a pre-migration backup as the rollback point, per-step
# downgrade functions where reversible, persisted history, and a
# compatibility guard against running old code on a newer schema.

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .config import CONFIG_DIR, SETTINGS_PATH, load_yaml, log, save_yaml

SCHEMA_STATE_PATH = os.path.join(CONFIG_DIR, "schema-version.json")


class MigrationError(RuntimeError):
    """Raised when migration cannot proceed (incompatible or failed state)."""


# --- Migration registry ---
# Each entry: version (dense, ascending), description, upgrade(), and an
# optional downgrade() for reversible steps. Upgrades must be idempotent —
# they may run again after a partial failure.

def _up_add_secrets_section() -> None:
    if not os.path.exists(SETTINGS_PATH):
        return  # fresh install: defaults (incl. secrets) come from config repair
    settings = load_yaml(SETTINGS_PATH)
    if "secrets" not in settings:
        settings["secrets"] = {"cloud_provider": "none", "vault_mount": "secret",
                               "azure_vault_name": "", "aws_region": ""}
        save_yaml(settings, SETTINGS_PATH)


def _down_remove_secrets_section() -> None:
    settings = load_yaml(SETTINGS_PATH)
    if settings.pop("secrets", None) is not None:
        save_yaml(settings, SETTINGS_PATH)


def _up_google_key_rename() -> None:
    # Historic rename: GOOGLE_API_KEY became GEMINI_API_KEY.
    from .config import get_windows_env, set_windows_env
    if not get_windows_env("GEMINI_API_KEY"):
        old = get_windows_env("GOOGLE_API_KEY")
        if old:
            log("INFO", "Migrating GOOGLE_API_KEY to GEMINI_API_KEY...")
            set_windows_env("GEMINI_API_KEY", old)


MIGRATIONS: List[Dict[str, Any]] = [
    {"version": 1, "description": "Rename GOOGLE_API_KEY to GEMINI_API_KEY",
     "upgrade": _up_google_key_rename, "downgrade": None},
    {"version": 2, "description": "Add secrets/cloud-vault section to settings.yaml",
     "upgrade": _up_add_secrets_section, "downgrade": _down_remove_secrets_section},
]


def latest_version() -> int:
    return MIGRATIONS[-1]["version"] if MIGRATIONS else 0


def _load_state() -> Dict[str, Any]:
    if os.path.exists(SCHEMA_STATE_PATH):
        try:
            with open(SCHEMA_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log("WARNING", f"Could not read schema state ({e}); assuming version 0.")
    return {"version": 0, "history": []}


def _save_state(state: Dict[str, Any]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SCHEMA_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def current_version() -> int:
    return int(_load_state().get("version", 0))


def _record(state: Dict[str, Any], version: int, description: str, direction: str) -> None:
    state["history"].append({
        "version": version, "description": description, "direction": direction,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def migrate(make_backup: Callable[[], Optional[str]] = None) -> int:
    """Apply all pending migrations. A configuration backup is taken first;
    on any failure the backup is restored (rollback) and MigrationError raised.
    Returns the number of migrations applied."""
    state = _load_state()
    pending = [m for m in MIGRATIONS if m["version"] > state["version"]]
    if not pending:
        return 0

    if make_backup is None:
        from .backup import cmd_backup
        make_backup = cmd_backup
    backup_zip = make_backup()
    if backup_zip:
        log("INFO", f"Pre-migration backup: {backup_zip}")

    applied = 0
    for m in pending:
        log("INFO", f"Applying migration v{m['version']}: {m['description']}")
        try:
            m["upgrade"]()
        except Exception as e:
            log("ERROR", f"Migration v{m['version']} failed: {e}")
            if backup_zip:
                _restore_backup(backup_zip)
                log("WARNING", "Configuration rolled back to the pre-migration backup. "
                               f"Schema remains at v{state['version']}.")
            raise MigrationError(f"Migration v{m['version']} failed: {e}") from e
        state["version"] = m["version"]
        _record(state, m["version"], m["description"], "upgrade")
        _save_state(state)  # persist after every step: reruns resume, not repeat
        applied += 1

    log("SUCCESS", f"Schema migrated to v{state['version']} ({applied} migration(s) applied).")
    return applied


def _restore_backup(backup_zip: str) -> None:
    try:
        from .backup import _restore_from_zip
        settings = load_yaml(SETTINGS_PATH)
        _restore_from_zip(backup_zip, os.path.dirname(backup_zip), settings)
    except Exception as e:
        log("ERROR", f"Automatic rollback restore failed: {e}. "
                     f"Restore manually from {backup_zip}.")


def rollback(target_version: int) -> int:
    """Walk downgrade functions from the current version back to target_version.
    Refuses if any migration in the range is irreversible."""
    state = _load_state()
    if target_version >= state["version"]:
        log("INFO", f"Nothing to roll back (current v{state['version']}, target v{target_version}).")
        return 0

    steps = [m for m in reversed(MIGRATIONS)
             if target_version < m["version"] <= state["version"]]
    irreversible = [m["version"] for m in steps if m["downgrade"] is None]
    if irreversible:
        raise MigrationError(
            f"Migrations {irreversible} have no downgrade path. "
            "Restore a pre-migration backup instead (Manage.bat restore).")

    for m in steps:
        log("INFO", f"Rolling back migration v{m['version']}: {m['description']}")
        m["downgrade"]()
        state["version"] = m["version"] - 1
        _record(state, m["version"], m["description"], "downgrade")
        _save_state(state)

    log("SUCCESS", f"Schema rolled back to v{state['version']}.")
    return len(steps)


def ensure_current() -> None:
    """Startup hook: validate compatibility and auto-apply pending migrations.

    A schema version NEWER than this build means the user downgraded the
    application — refuse to touch state we do not understand."""
    state = _load_state()
    if state["version"] > latest_version():
        raise MigrationError(
            f"Configuration schema v{state['version']} is newer than this AIRM build "
            f"(v{latest_version()}). Upgrade AIRM or restore an older backup.")
    if state["version"] < latest_version():
        migrate()


def status() -> Dict[str, Any]:
    """Migration status: current/latest versions, pending list, history."""
    state = _load_state()
    return {
        "current_version": state["version"],
        "latest_version": latest_version(),
        "pending": [{"version": m["version"], "description": m["description"],
                     "reversible": m["downgrade"] is not None}
                    for m in MIGRATIONS if m["version"] > state["version"]],
        "history": state.get("history", []),
    }
