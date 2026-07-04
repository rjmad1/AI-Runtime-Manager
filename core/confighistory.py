# core/confighistory.py
# Configuration versioning for AIRM.
# Every write to a versioned YAML config snapshots the previous version:
# change history, diff, rollback, tags, and detection of out-of-band edits.
# Hooked into config.save_yaml — the single choke point for config writes.

import difflib
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import CONFIG_DIR, log

HISTORY_DIR = os.path.join(CONFIG_DIR, "history")
INDEX_PATH = os.path.join(HISTORY_DIR, "index.json")
VERSIONED_FILES = ("settings.yaml", "providers.yaml", "models.yaml")
MAX_SNAPSHOTS_PER_FILE = 100


def _is_versioned(path: str) -> bool:
    return (os.path.basename(path) in VERSIONED_FILES
            and os.path.abspath(os.path.dirname(path)) == os.path.abspath(CONFIG_DIR))


def _sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _load_index() -> Dict[str, Any]:
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log("WARNING", "Config history index unreadable; starting a fresh index.")
    return {"next_id": 1, "entries": [], "heads": {}}


def _save_index(index: Dict[str, Any]) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def _audit(event: str, name: str) -> None:
    from .secretstore import audit  # lazy: avoid import cycles at module load
    audit(event, name, provider="config-history")


def _prune(index: Dict[str, Any], filename: str) -> None:
    """Keep the newest MAX_SNAPSHOTS_PER_FILE snapshots per file."""
    entries = [e for e in index["entries"] if e["file"] == filename]
    for old in entries[:-MAX_SNAPSHOTS_PER_FILE]:
        snap = os.path.join(HISTORY_DIR, old["snapshot"])
        if os.path.exists(snap):
            os.remove(snap)
        index["entries"].remove(old)


def before_save(path: str, new_content: Optional[str] = None) -> None:
    """Snapshot the current on-disk version before it is overwritten and
    detect out-of-band edits (file changed since AIRM last wrote it).

    When new_content is provided and matches the on-disk bytes, the write is
    a no-op and produces no history entry."""
    try:
        if not _is_versioned(path) or not os.path.exists(path):
            return
        filename = os.path.basename(path)
        index = _load_index()
        current_sha = _sha256_file(path)

        if new_content is not None:
            # Text compare with universal newlines: byte hashes differ on
            # Windows (\r\n on disk vs \n in the serialized string).
            with open(path, "r", encoding="utf-8") as f:
                if f.read() == new_content:
                    return  # nothing changes: no snapshot, no conflict noise

        last_written = index["heads"].get(filename)
        conflict = bool(last_written) and last_written != current_sha
        if conflict:
            log("WARNING", f"Conflict detected: {filename} was modified outside AIRM "
                           "since its last managed write. The external version is being "
                           "preserved in history before this save overwrites it.")
            _audit("config-conflict", filename)

        # Skip duplicate snapshots of identical content
        prior = [e for e in index["entries"] if e["file"] == filename]
        if prior and prior[-1]["sha256"] == current_sha:
            return

        entry_id = index["next_id"]
        snapshot_name = f"{entry_id:06d}_{filename}"
        os.makedirs(HISTORY_DIR, exist_ok=True)
        shutil.copy2(path, os.path.join(HISTORY_DIR, snapshot_name))
        index["next_id"] = entry_id + 1
        index["entries"].append({
            "id": entry_id, "file": filename, "snapshot": snapshot_name,
            "sha256": current_sha, "tag": "",
            "conflict": conflict,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        _prune(index, filename)
        _save_index(index)
        _audit("config-snapshot", filename)
    except Exception as e:
        # History must never block a configuration write
        log("WARNING", f"Config history snapshot failed for {path}: {e}")


def after_save(path: str) -> None:
    """Record the hash of what AIRM just wrote (conflict-detection baseline)."""
    try:
        if not _is_versioned(path) or not os.path.exists(path):
            return
        index = _load_index()
        index["heads"][os.path.basename(path)] = _sha256_file(path)
        _save_index(index)
    except Exception as e:
        log("WARNING", f"Config history head update failed for {path}: {e}")


def history_list(filename: str = "") -> List[Dict[str, Any]]:
    """Chronological history entries, optionally filtered to one file."""
    entries = _load_index()["entries"]
    if filename:
        entries = [e for e in entries if e["file"] == filename]
    return entries


def _entry(entry_id: int) -> Optional[Dict[str, Any]]:
    for e in _load_index()["entries"]:
        if e["id"] == entry_id:
            return e
    return None


def diff(entry_id: int) -> str:
    """Unified diff: snapshot <entry_id> → current live file."""
    entry = _entry(entry_id)
    if not entry:
        return f"No history entry with id {entry_id}."
    snap_path = os.path.join(HISTORY_DIR, entry["snapshot"])
    live_path = os.path.join(CONFIG_DIR, entry["file"])
    old = open(snap_path, encoding="utf-8").read().splitlines(keepends=True) \
        if os.path.exists(snap_path) else []
    new = open(live_path, encoding="utf-8").read().splitlines(keepends=True) \
        if os.path.exists(live_path) else []
    return "".join(difflib.unified_diff(
        old, new, fromfile=f"{entry['file']}@v{entry_id}", tofile=f"{entry['file']}@current"))


def rollback(entry_id: int) -> bool:
    """Restore a snapshot over the live file. The pre-rollback state is
    snapshotted first, so a rollback is itself reversible."""
    entry = _entry(entry_id)
    if not entry:
        log("ERROR", f"No history entry with id {entry_id}.")
        return False
    snap_path = os.path.join(HISTORY_DIR, entry["snapshot"])
    if not os.path.exists(snap_path):
        log("ERROR", f"Snapshot file for entry {entry_id} is missing.")
        return False
    live_path = os.path.join(CONFIG_DIR, entry["file"])

    before_save(live_path)  # preserve what we are about to replace
    shutil.copy2(snap_path, live_path)
    after_save(live_path)
    _audit("config-rollback", entry["file"])
    log("SUCCESS", f"Rolled {entry['file']} back to history entry {entry_id} "
                   f"({entry['ts']}). Run 'configure' to recompile blueprints.")
    return True


def tag(entry_id: int, label: str) -> bool:
    """Attach a human label (e.g. 'known-good', 'pre-gpu-tuning') to an entry."""
    index = _load_index()
    for e in index["entries"]:
        if e["id"] == entry_id:
            e["tag"] = label[:60]
            _save_index(index)
            _audit("config-tagged", f"{e['file']}#{entry_id}")
            return True
    log("ERROR", f"No history entry with id {entry_id}.")
    return False
