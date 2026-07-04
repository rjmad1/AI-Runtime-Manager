# core/secretstore.py
# Secure credential management for AIRM.
# Secrets live in the native OS credential store; reads fall through to an
# optional cloud vault CLI and finally to environment variables. All access
# is audit-logged (event + name only — never values).

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import LOGS_DIR, SETTINGS_PATH, load_yaml, log

_TARGET_PREFIX = "AIRM/"
AUDIT_LOG = os.path.join(LOGS_DIR, "audit.log")

# pywin32 (already a Windows dependency) exposes the Windows Credential
# Manager, which encrypts blobs at rest with DPAPI under the user's key.
try:
    import pywintypes
    import win32cred
    HAS_WIN32CRED = True
except ImportError:
    HAS_WIN32CRED = False


def audit(event: str, name: str, provider: str = "", ok: bool = True) -> None:
    """Append a JSON audit record. Records carry names and outcomes, never values."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event, "name": name, "provider": provider, "ok": ok,
    }
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # auditing must never break secret access


# --- OS credential store backends ---

def _win_get(name: str) -> Optional[str]:
    try:
        cred = win32cred.CredRead(_TARGET_PREFIX + name, win32cred.CRED_TYPE_GENERIC)
        return cred["CredentialBlob"].decode("utf-16-le")
    except pywintypes.error:
        return None  # not found


def _win_set(name: str, value: str) -> bool:
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": _TARGET_PREFIX + name,
        "UserName": "AIRM",
        "CredentialBlob": value,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
    }, 0)
    return True


def _win_delete(name: str) -> bool:
    try:
        win32cred.CredDelete(_TARGET_PREFIX + name, win32cred.CRED_TYPE_GENERIC)
        return True
    except pywintypes.error:
        return False


def _mac_get(name: str) -> Optional[str]:
    res = subprocess.run(
        ["security", "find-generic-password", "-a", "AIRM", "-s", _TARGET_PREFIX + name, "-w"],
        capture_output=True, text=True)
    return (res.stdout.strip() or None) if res.returncode == 0 else None


def _mac_set(name: str, value: str) -> bool:
    # -U updates in place; value passes on argv (Keychain CLI has no stdin mode)
    res = subprocess.run(
        ["security", "add-generic-password", "-a", "AIRM", "-s", _TARGET_PREFIX + name,
         "-w", value, "-U"], capture_output=True, text=True)
    return res.returncode == 0


def _mac_delete(name: str) -> bool:
    res = subprocess.run(
        ["security", "delete-generic-password", "-a", "AIRM", "-s", _TARGET_PREFIX + name],
        capture_output=True, text=True)
    return res.returncode == 0


def _linux_get(name: str) -> Optional[str]:
    if not shutil.which("secret-tool"):
        return None
    res = subprocess.run(["secret-tool", "lookup", "service", "AIRM", "name", name],
                         capture_output=True, text=True)
    return (res.stdout.strip() or None) if res.returncode == 0 else None


def _linux_set(name: str, value: str) -> bool:
    if not shutil.which("secret-tool"):
        return False
    res = subprocess.run(
        ["secret-tool", "store", f"--label=AIRM {name}", "service", "AIRM", "name", name],
        input=value, capture_output=True, text=True)
    return res.returncode == 0


def _linux_delete(name: str) -> bool:
    if not shutil.which("secret-tool"):
        return False
    res = subprocess.run(["secret-tool", "clear", "service", "AIRM", "name", name],
                         capture_output=True, text=True)
    return res.returncode == 0


def _os_backend():
    """Return (provider_name, get, set, delete) for this platform, or None."""
    system = platform.system()
    if system == "Windows" and HAS_WIN32CRED:
        return ("windows-credential-manager", _win_get, _win_set, _win_delete)
    if system == "Darwin" and shutil.which("security"):
        return ("macos-keychain", _mac_get, _mac_set, _mac_delete)
    if system == "Linux" and shutil.which("secret-tool"):
        return ("linux-secret-service", _linux_get, _linux_set, _linux_delete)
    return None


# --- Cloud vault read-through (CLI based: no SDK dependencies) ---

def _cloud_get(name: str, cfg: Dict[str, Any]) -> Optional[str]:
    """Read a secret from the configured cloud vault via its official CLI.

    Read-only by design: writes/rotation in enterprise vaults stay with the
    vault's own tooling and access policies (least privilege)."""
    provider = cfg.get("cloud_provider", "none")
    try:
        if provider == "vault" and shutil.which("vault"):
            mount = cfg.get("vault_mount", "secret")
            res = subprocess.run(
                ["vault", "kv", "get", f"-mount={mount}", "-field=value", f"airm/{name}"],
                capture_output=True, text=True, timeout=15)
            return (res.stdout.strip() or None) if res.returncode == 0 else None
        if provider == "azure" and shutil.which("az"):
            vault_name = cfg.get("azure_vault_name", "")
            if not vault_name:
                return None
            res = subprocess.run(
                ["az", "keyvault", "secret", "show", "--vault-name", vault_name,
                 "--name", name.replace("_", "-"), "--query", "value", "-o", "tsv"],
                capture_output=True, text=True, timeout=30)
            return (res.stdout.strip() or None) if res.returncode == 0 else None
        if provider == "aws" and shutil.which("aws"):
            cmd = ["aws", "secretsmanager", "get-secret-value", "--secret-id", f"airm/{name}",
                   "--query", "SecretString", "--output", "text"]
            region = cfg.get("aws_region", "")
            if region:
                cmd += ["--region", region]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return (res.stdout.strip() or None) if res.returncode == 0 else None
    except Exception as e:
        log("WARNING", f"Cloud vault lookup for {name} failed: {e}")
    return None


def _secrets_settings() -> Dict[str, Any]:
    return load_yaml(SETTINGS_PATH).get("secrets", {})


# --- Public API ---

def get_secret(name: str) -> Optional[str]:
    """Resolve a secret: OS credential store → cloud vault → None.

    Environment fallback is handled by the caller (config.get_windows_env)
    to preserve the legacy resolution order."""
    backend = _os_backend()
    if backend:
        provider, getter, _, _ = backend
        try:
            value = getter(name)
            if value:
                return value
        except Exception as e:
            log("WARNING", f"OS credential store read failed for {name}: {e}")

    cfg = _secrets_settings()
    if cfg.get("cloud_provider", "none") != "none":
        value = _cloud_get(name, cfg)
        if value:
            audit("read", name, provider=cfg["cloud_provider"])
            return value
    return None


def set_secret(name: str, value: str) -> bool:
    """Store a secret in the OS credential store. Overwriting an existing
    value is the rotation path and is audit-logged as such."""
    backend = _os_backend()
    if not backend:
        audit("write", name, provider="none", ok=False)
        return False
    provider, getter, setter, _ = backend
    try:
        existed = bool(getter(name))
        ok = setter(name, value)
        audit("rotate" if existed else "write", name, provider=provider, ok=ok)
        return ok
    except Exception as e:
        log("ERROR", f"Failed to store secret {name}: {e}")
        audit("write", name, provider=provider, ok=False)
        return False


def delete_secret(name: str) -> bool:
    """Remove a secret from the OS credential store."""
    backend = _os_backend()
    if not backend:
        return False
    provider, _, _, deleter = backend
    ok = deleter(name)
    audit("delete", name, provider=provider, ok=ok)
    return ok


def migrate_legacy(name: str, value: str) -> None:
    """Promote a secret found in a legacy plaintext location (registry env /
    ~/.airm_env) into the OS credential store. The legacy copy is left in
    place — removing it is the user's call (see 'secret' CLI docs)."""
    if set_secret(name, value):
        audit("migrated-from-legacy", name)
        log("INFO", f"Migrated {name} from legacy environment storage into the OS credential store.")


def describe_secret(name: str) -> str:
    """Report where a secret currently resolves from (for 'secret list')."""
    backend = _os_backend()
    if backend:
        provider, getter, _, _ = backend
        try:
            if getter(name):
                return provider
        except Exception:
            pass
    cfg = _secrets_settings()
    if cfg.get("cloud_provider", "none") != "none" and _cloud_get(name, cfg):
        return cfg["cloud_provider"]
    if os.environ.get(name):
        return "environment (legacy)"
    return "not set"
