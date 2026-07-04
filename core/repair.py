# core/repair.py
# Inventory-driven dependency remediation for AIRM.
# Consumes the Capability-1 dependency inventory (core/discovery.py) and
# installs, validates, and reports on missing dependencies.

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import GENERATED_DIR, log

# Remediation strategy per inventory item.
#   winget/brew : package id for silent auto-install (with user consent)
#   bundled_with: comes with another managed dependency
#   manual      : guidance only — too heavy/privileged to install silently
STRATEGIES: Dict[str, Dict[str, str]] = {
    "git":    {"winget": "Git.Git", "brew": "git"},
    "python": {"winget": "Python.Python.3.12", "brew": "python@3.12"},
    "node":   {"winget": "OpenJS.NodeJS.LTS", "brew": "node"},
    "npm":    {"bundled_with": "node"},
    "uv":     {"winget": "astral-sh.uv", "brew": "uv"},
    "ollama": {"winget": "Ollama.Ollama", "brew": "ollama"},
    "java":   {"manual": "Install a JDK from https://adoptium.net/"},
    "docker": {"manual": "Install Docker from https://docs.docker.com/get-docker/"},
    "wsl":    {"manual": "Run 'wsl --install' from an elevated PowerShell"},
    "cuda":   {"manual": "Install the CUDA Toolkit from https://developer.nvidia.com/cuda-downloads"},
    "rocm":   {"manual": "Install ROCm from https://rocm.docs.amd.com/"},
    "nvidia-driver": {"manual": "Install the NVIDIA driver from https://www.nvidia.com/drivers"},
    "virtualization": {"manual": "Enable hardware virtualization (VT-x / AMD-V) in BIOS/UEFI"},
}

_INSTALL_TIMEOUT_SECONDS = 900


def _pkg_manager() -> Tuple[Optional[str], Optional[str]]:
    """Return (manager_name, executable) for this platform's package manager.

    Linux intentionally returns (None, None): apt/dnf need sudo and vary by
    distro, so Linux remediation is guidance-only."""
    system = platform.system()
    if system == "Windows":
        exe = shutil.which("winget")
        return ("winget", exe) if exe else (None, None)
    if system == "Darwin":
        exe = shutil.which("brew")
        return ("brew", exe) if exe else (None, None)
    return (None, None)


def _refresh_windows_path() -> None:
    """Merge the registry Machine+User PATH into this process so tools
    installed moments ago by winget become resolvable without a new shell."""
    from .discovery import run_powershell_cmd
    out = run_powershell_cmd(
        "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + "
        "[Environment]::GetEnvironmentVariable('Path','User')"
    )
    current = os.environ.get("PATH", "")
    for entry in out.split(";"):
        entry = entry.strip()
        if entry and entry not in current:
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + entry


def _validate_installed(name: str) -> Dict[str, str]:
    """Re-probe a dependency after install; return {} if still not found."""
    from . import discovery
    if platform.system() == "Windows":
        _refresh_windows_path()
    path = shutil.which(name) or discovery.discover_tools().get(name, "")
    if not path:
        return {}
    return {"path": path, "version": discovery._probe_version([path, "--version"])}


def install_dependency(name: str, mgr_name: str, mgr_exe: str) -> Dict[str, Any]:
    """Install one dependency via the platform package manager and validate it.

    winget and brew are transactional installers: a failed install rolls
    itself back, so a non-zero exit leaves the system unchanged."""
    pkg = STRATEGIES[name][mgr_name]
    if mgr_name == "winget":
        cmd = [mgr_exe, "install", "--id", pkg, "-e", "--silent",
               "--accept-source-agreements", "--accept-package-agreements"]
    else:
        cmd = [mgr_exe, "install", pkg]

    log("INFO", f"Installing '{name}' via {mgr_name} ({pkg})...")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_SECONDS)
    except Exception as e:
        log("ERROR", f"Installer for '{name}' could not run: {e}")
        return {"name": name, "status": "failed", "details": str(e)}

    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()[-300:]
        log("ERROR", f"Install of '{name}' failed (exit {res.returncode}). {mgr_name} rolled back. {detail}")
        return {"name": name, "status": "failed", "details": detail}

    probe = _validate_installed(name)
    if probe:
        log("SUCCESS", f"Repaired '{name}': v{probe['version']} at {probe['path']}")
        return {"name": name, "status": "repaired", **probe}

    # Installer succeeded but the binary is not yet resolvable — almost always
    # a PATH propagation issue, so do NOT uninstall a likely-good install.
    log("WARNING", f"'{name}' installed but not yet on PATH. Restart the shell and re-run inventory.")
    return {"name": name, "status": "installed_unverified",
            "details": "Installed; restart the shell to pick up PATH changes."}


def repair_dependencies(interactive: bool = True) -> List[Dict[str, Any]]:
    """Remediate missing dependencies from the enterprise inventory.

    interactive=True  : ask consent per auto-installable dependency, then install.
    interactive=False : plan only — report what would be installed and how.
    Writes an audit report to generated/repair-report.json either way."""
    from . import discovery

    log("INFO", "Dependency Auditing: checking enterprise dependency inventory...")
    inventory = discovery.discover_dependency_inventory()
    missing = [i["name"] for i in inventory["items"] if i["status"] != "present"]

    if not missing:
        log("SUCCESS", "All inventoried dependencies are present.")
        _write_report([])
        return []

    mgr_name, mgr_exe = _pkg_manager()
    auto = {n for n in missing if mgr_exe and STRATEGIES.get(n, {}).get(mgr_name)}
    if "node" in auto:
        auto.discard("npm")  # npm ships with node; one install fixes both

    results: List[Dict[str, Any]] = []
    for name in missing:
        strat = STRATEGIES.get(name, {})
        if name in auto:
            if not interactive:
                log("WARNING", f"'{name}' is missing. Run 'Manage.bat repair' interactively to install via {mgr_name}.")
                results.append({"name": name, "status": "pending_consent",
                                "details": f"auto-installable via {mgr_name}"})
                continue
            answer = input(f"Install missing dependency '{name}' via {mgr_name}? (yes/no): ").strip().lower()
            if answer != "yes":
                log("INFO", f"Skipped install of '{name}' by user choice.")
                results.append({"name": name, "status": "skipped", "details": "declined by user"})
                continue
            results.append(install_dependency(name, mgr_name, mgr_exe))
        else:
            bundled = strat.get("bundled_with")
            if strat.get("manual"):
                guidance = strat["manual"]
            elif bundled:
                guidance = f"Installed together with '{bundled}'"
            elif "winget" in strat or "brew" in strat:
                guidance = ("Auto-installable, but no package manager was found "
                            "(winget on Windows, Homebrew on macOS). Install one or install manually.")
            else:
                guidance = "No automated remediation strategy"
            log("WARNING", f"'{name}' is missing. {guidance}")
            results.append({"name": name, "status": "manual", "details": guidance})

    _write_report(results)
    return results


def upgrade_managed_runtimes() -> None:
    """Upgrade AIRM-managed AI runtimes via the platform package manager.

    ponytail: only ollama for now — system toolchain (git/node/python) upgrades
    stay with the OS package manager; extend STRATEGIES lookup if that changes."""
    mgr_name, mgr_exe = _pkg_manager()
    if not mgr_exe or not shutil.which("ollama"):
        return
    log("INFO", f"Checking for Ollama upgrades via {mgr_name}...")
    pkg = STRATEGIES["ollama"][mgr_name]
    cmd = ([mgr_exe, "upgrade", "--id", pkg, "-e", "--silent",
            "--accept-source-agreements", "--accept-package-agreements"]
           if mgr_name == "winget" else [mgr_exe, "upgrade", pkg])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_SECONDS)
        if res.returncode == 0:
            log("SUCCESS", "Ollama is up to date.")
        else:
            log("INFO", "No Ollama upgrade applied (already current or unavailable).")
    except Exception as e:
        log("WARNING", f"Ollama upgrade check failed: {e}")


def _write_report(results: List[Dict[str, Any]]) -> None:
    """Persist the remediation audit report next to the dependency inventory."""
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": results,
    }
    try:
        path = os.path.join(GENERATED_DIR, "repair-report.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        log("INFO", f"Remediation report written to {path}")
    except Exception as e:
        log("WARNING", f"Could not write remediation report: {e}")
