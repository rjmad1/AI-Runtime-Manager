# core/service.py
# OS service integration: run the AIRM watchdog as a Windows Service or a
# systemd user unit so the stack auto-starts at boot and survives crashes.
# The service supervises the watchdog; the watchdog supervises the daemons.

import os
import platform
import subprocess
import sys

from .config import ROOT_DIR, log

SERVICE_NAME = "AIRM"
SERVICE_DISPLAY = "AIRM AI Runtime Manager"
SERVICE_DESC = "Self-healing watchdog supervising the LiteLLM proxy and OpenClaw gateway."

SERVICE_ACTIONS = ("install", "uninstall", "start", "stop", "status")

# pywin32 is a Windows-only optional dependency; this module must still import
# cleanly on Linux/macOS and on Windows before dependencies are installed.
try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False


if HAS_PYWIN32:

    class AirmService(win32serviceutil.ServiceFramework):
        """Windows Service wrapper around the AIRM watchdog loop."""

        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY
        _svc_description_ = SERVICE_DESC

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):  # noqa: N802 - pywin32 API name
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):  # noqa: N802 - pywin32 API name
            # Start/stop/crash all land in the Windows Event Log (Application).
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                  servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ""))
            from .process import watch_loop
            try:
                watch_loop(
                    wait=lambda s: win32event.WaitForSingleObject(self.stop_event, int(s * 1000)),
                    should_stop=lambda: win32event.WaitForSingleObject(
                        self.stop_event, 0) == win32event.WAIT_OBJECT_0,
                )
            except Exception as e:
                servicemanager.LogErrorMsg(f"{SERVICE_NAME} watchdog crashed: {e}")
                raise
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                  servicemanager.PYS_SERVICE_STOPPED, (self._svc_name_, ""))


# --- Windows ---

def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _require_pywin32() -> bool:
    if not HAS_PYWIN32:
        log("ERROR", "pywin32 is not installed. Run 'Manage.bat repair' or "
                     "'pip install pywin32' inside the .venv, then retry.")
        return False
    return True


def _windows_install() -> None:
    if not _require_pywin32():
        return
    if not _is_admin():
        log("ERROR", "Service installation requires an elevated (Administrator) console.")
        return

    # Register pywin32 DLLs so pythonservice.exe can run from this venv.
    try:
        subprocess.run([sys.executable, "-m", "pywin32_postinstall", "-install", "-silent"],
                       capture_output=True, text=True, timeout=120)
    except Exception as e:
        log("WARNING", f"pywin32 post-install step failed (continuing): {e}")

    try:
        win32serviceutil.InstallService(
            win32serviceutil.GetServiceClassString(AirmService),
            SERVICE_NAME, SERVICE_DISPLAY,
            startType=win32service.SERVICE_AUTO_START,
            description=SERVICE_DESC,
        )
    except Exception as e:
        log("ERROR", f"Failed to install Windows service: {e}")
        return

    # Recovery policy: restart after 5s/10s/30s on failure, counters reset
    # daily. Delayed auto-start so the network stack is up before the watchdog.
    subprocess.run(["sc", "failure", SERVICE_NAME, "reset=", "86400",
                    "actions=", "restart/5000/restart/10000/restart/30000"], capture_output=True)
    subprocess.run(["sc", "config", SERVICE_NAME, "start=", "delayed-auto"], capture_output=True)

    log("SUCCESS", f"Windows service '{SERVICE_NAME}' installed (delayed auto-start, "
                   "restart-on-failure, Event Log integration).")
    log("WARNING", "The service runs as LocalSystem: provider API keys stored as USER "
                   "environment variables are not visible to it. Either set the keys at "
                   "Machine scope, or set the service to run as your account in "
                   "services.msc (Log On tab).")


def _windows_uninstall() -> None:
    if not _require_pywin32():
        return
    if not _is_admin():
        log("ERROR", "Service removal requires an elevated (Administrator) console.")
        return
    try:
        try:
            win32serviceutil.StopService(SERVICE_NAME)
        except Exception:
            pass  # already stopped or never started
        win32serviceutil.RemoveService(SERVICE_NAME)
        log("SUCCESS", f"Windows service '{SERVICE_NAME}' removed.")
    except Exception as e:
        log("ERROR", f"Failed to remove Windows service: {e}")


_WIN_STATE_NAMES = {1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING", 4: "RUNNING",
                    5: "CONTINUE_PENDING", 6: "PAUSE_PENDING", 7: "PAUSED"}


def _windows_status() -> None:
    if not _require_pywin32():
        return
    try:
        state = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        log("INFO", f"Service '{SERVICE_NAME}': {_WIN_STATE_NAMES.get(state, state)}")
    except Exception:
        log("INFO", f"Service '{SERVICE_NAME}' is not installed. Run 'Manage.bat service install' from an elevated console.")


def _windows(action: str) -> None:
    if action == "install":
        _windows_install()
    elif action == "uninstall":
        _windows_uninstall()
    elif action == "status":
        _windows_status()
    elif not _require_pywin32():
        return
    else:
        try:
            if action == "start":
                win32serviceutil.StartService(SERVICE_NAME)
                log("SUCCESS", f"Service '{SERVICE_NAME}' started.")
            else:
                win32serviceutil.StopService(SERVICE_NAME)
                log("SUCCESS", f"Service '{SERVICE_NAME}' stopped.")
        except Exception as e:
            log("ERROR", f"Service {action} failed: {e}")


# --- Linux (systemd user unit: no root required, per-user stack) ---

SYSTEMD_UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
SYSTEMD_UNIT_NAME = "airm.service"


def systemd_unit() -> str:
    """Render the systemd user unit for the AIRM watchdog."""
    return (
        "[Unit]\n"
        f"Description={SERVICE_DESC}\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={sys.executable} -m core.manager watch\n"
        f"WorkingDirectory={ROOT_DIR}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def _linux(action: str) -> None:
    unit_path = os.path.join(SYSTEMD_UNIT_DIR, SYSTEMD_UNIT_NAME)

    if action == "install":
        os.makedirs(SYSTEMD_UNIT_DIR, exist_ok=True)
        with open(unit_path, "w", encoding="utf-8") as f:
            f.write(systemd_unit())
        _systemctl("daemon-reload")
        res = _systemctl("enable", "--now", SYSTEMD_UNIT_NAME)
        if res.returncode != 0:
            log("ERROR", f"systemd enable failed: {(res.stderr or res.stdout).strip()}")
            return
        # Best effort: let the unit run at boot without an active login session.
        subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")],
                       capture_output=True)
        log("SUCCESS", f"systemd user unit installed and started: {unit_path} "
                       "(Restart=on-failure, enabled at boot).")
    elif action == "uninstall":
        _systemctl("disable", "--now", SYSTEMD_UNIT_NAME)
        if os.path.exists(unit_path):
            os.remove(unit_path)
        _systemctl("daemon-reload")
        log("SUCCESS", f"systemd user unit '{SYSTEMD_UNIT_NAME}' removed.")
    elif action in ("start", "stop"):
        res = _systemctl(action, SYSTEMD_UNIT_NAME)
        if res.returncode == 0:
            log("SUCCESS", f"Service '{SYSTEMD_UNIT_NAME}' {action} completed.")
        else:
            log("ERROR", f"systemctl {action} failed: {(res.stderr or res.stdout).strip()}")
    else:  # status
        res = _systemctl("status", SYSTEMD_UNIT_NAME, "--no-pager")
        print(res.stdout or res.stderr)


def cmd_service(action: str) -> None:
    """Manage the AIRM OS service (Windows Service / systemd user unit).

    The service hosts the self-healing watchdog: two-tier supervision where the
    OS restarts the watchdog and the watchdog restarts the daemons. Stopping
    the service stops supervision only — use 'stop' to stop the daemons."""
    if action not in SERVICE_ACTIONS:
        log("ERROR", f"Unknown service action '{action}'. Use one of: {', '.join(SERVICE_ACTIONS)}")
        return

    system = platform.system()
    if system == "Windows":
        _windows(action)
    elif system == "Linux":
        _linux(action)
    else:
        log("ERROR", "OS service integration supports Windows (Windows Service) and Linux "
                     "(systemd). On macOS, run 'manage.sh watch' or create a launchd agent manually.")
