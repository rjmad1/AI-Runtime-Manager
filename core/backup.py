# core/backup.py
# Configuration backup and restore for AIRM.

import os
import sys
import json
import shutil
import zipfile
from datetime import datetime
from typing import Optional

import config
from config import (
    log, load_yaml, cmd_configure,
)

OPENCLAW_JSON_FILE = "openclaw.json"


def cmd_backup() -> Optional[str]:
    """Create a timestamped ZIP backup of active configurations."""
    log("INFO", "Creating system configurations backup...")
    settings = load_yaml(config.SETTINGS_PATH)
    backup_dir: str = settings.get("lifecycle", {}).get("backup_dir", "backups")
    backup_dir = os.path.abspath(os.path.join(config.ROOT_DIR, backup_dir))
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(backup_dir, f"openclaw_backup_{timestamp}.zip")

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in ["settings.yaml", "providers.yaml", "models.yaml"]:
                fp = os.path.join(config.CONFIG_DIR, file)
                if os.path.exists(fp):
                    zipf.write(fp, arcname=os.path.join("OpenClawManager", file))
            for file in ["config.yaml", OPENCLAW_JSON_FILE]:
                fp = os.path.join(config.GENERATED_DIR, file)
                if os.path.exists(fp):
                    zipf.write(fp, arcname=os.path.join("generated", file))
            claw_home_dir: str = settings.get("openclaw", {}).get("config_dir") or ""
            if not claw_home_dir:
                claw_home_dir = os.path.join(os.path.expanduser("~"), ".openclaw")
            claw_json = os.path.join(claw_home_dir, OPENCLAW_JSON_FILE)
            if os.path.exists(claw_json):
                zipf.write(claw_json, arcname="active_openclaw.json")
        log("SUCCESS", f"Backup archive created successfully: {zip_path}")
        return zip_path
    except Exception as e:
        log("ERROR", f"Failed to create backup: {e}")
        return None
def _restore_from_zip(target_zip: str, backup_dir: str, settings: dict) -> None:
    """Helper function to extract and restore from zip."""
    temp_dir = os.path.join(backup_dir, "temp_restore")
    os.makedirs(temp_dir, exist_ok=True)

    with zipfile.ZipFile(target_zip, "r") as zipf:
        # Zip Slip Prevention
        for member in zipf.infolist():
            target_path = os.path.abspath(os.path.join(temp_dir, member.filename))
            if not target_path.startswith(os.path.abspath(temp_dir)):
                raise ValueError(
                    f"Security Warning: Path traversal detected in zip archive file: {member.filename}"
                )
        zipf.extractall(temp_dir)

    for f in ["settings.yaml", "providers.yaml", "models.yaml"]:
        src = os.path.join(temp_dir, "OpenClawManager", f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(config.CONFIG_DIR, f))

    claw_home_dir: str = settings.get("openclaw", {}).get("config_dir") or ""
    if not claw_home_dir:
        claw_home_dir = os.path.join(os.path.expanduser("~"), ".openclaw")

    src_active = os.path.join(temp_dir, "active_openclaw.json")
    if os.path.exists(src_active):
        shutil.copy2(src_active, os.path.join(claw_home_dir, OPENCLAW_JSON_FILE))

    shutil.rmtree(temp_dir)


def cmd_restore(backup_idx: Optional[int] = None) -> bool:
    """Restore configurations from a backup archive.

    If backup_idx is None, prompts the user interactively.
    """
    log("INFO", "Running configuration restore interface...")
    settings = load_yaml(config.SETTINGS_PATH)
    backup_dir: str = settings.get("lifecycle", {}).get("backup_dir", "backups")
    backup_dir = os.path.abspath(os.path.join(config.ROOT_DIR, backup_dir))

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
        _restore_from_zip(target_zip, backup_dir, settings)
        log("SUCCESS", "Configurations successfully restored.")
        cmd_configure()
        return True
    except Exception as e:
        log("ERROR", f"Failed to restore configurations: {e}")
        return False
