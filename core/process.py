# core/process.py
# Process lifecycle, port management, and service daemon control for AIRM.

import json
import os
import platform
import subprocess
import tempfile
import time
import urllib.request
from typing import Any, Dict, List, Optional

import psutil

from .config import (
    LITELLM_CONFIG_PATH,
    LOGS_DIR,
    PROVIDERS_PATH,
    ROOT_DIR,
    SERVICES_STATE_PATH,
    SETTINGS_PATH,
    cmd_configure,
    get_windows_env,
    load_yaml,
    log,
)


class ProcessLock:
    def __init__(self, name: str):
        self.lock_file = os.path.join(tempfile.gettempdir(), f"airm_{name}.lock")
        self.fd: Any = None

    def acquire(self) -> bool:
        try:
            self.fd = open(self.lock_file, 'w')
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore
            return True
        except (IOError, OSError, ImportError):
            if self.fd:
                self.fd.close()
                self.fd = None
            return False

    def release(self) -> None:
        if self.fd:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self.fd.seek(0)
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd, fcntl.LOCK_UN)  # type: ignore
            except Exception:
                pass
            finally:
                self.fd.close()
                self.fd = None



def load_services_state() -> Dict[str, Optional[int]]:
    """Load tracked daemon PIDs from services.json."""
    if os.path.exists(SERVICES_STATE_PATH):
        try:
            with open(SERVICES_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"litellm": None, "openclaw": None}


def save_services_state(state: Dict[str, Optional[int]]) -> None:
    """Persist daemon PIDs to services.json."""
    try:
        with open(SERVICES_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log("ERROR", f"Failed to save services state: {e}")


def get_pids_on_port(port: int) -> List[int]:
    """Return PIDs listening on a given TCP port."""
    pids: set = set()
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr and conn.laddr[1] == port and conn.status == 'LISTEN':
                if conn.pid is not None:
                    pids.add(conn.pid)
        return list(pids)
    except psutil.AccessDenied:
        pass
    except Exception as e:
        log("WARNING", f"Could not list TCP connections via psutil: {e}")

    return _get_pids_on_port_fallback(port, pids)

def _get_pids_on_port_fallback(port: int, pids: set) -> List[int]:
    """Fallback for Windows without elevation."""
    if platform.system() == "Windows":
        try:
            out = subprocess.check_output(["netstat", "-ano"], text=True)
            for line in out.splitlines():
                if f":{port}" in line and "LISTEN" in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = int(parts[-1])
                        if pid > 0:
                            pids.add(pid)
        except Exception as e:
            log("WARNING", f"netstat fallback failed: {e}")
    return list(pids)


def is_pid_running(pid: Optional[int]) -> bool:
    """Check whether a PID is currently active."""
    if not pid:
        return False
    return psutil.pid_exists(pid)


def kill_process_tree(pid: int) -> bool:
    """Gracefully terminate a process tree, falling back to force kill."""
    try:
        if not is_pid_running(pid):
            return True
        log("INFO", f"Terminating PID {pid} and its children gracefully...")

        parent = psutil.Process(pid)
        children = parent.children(recursive=True)

        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()

        _, alive = psutil.wait_procs(children + [parent], timeout=3)
        for p in alive:
            log("WARNING", f"PID {p.pid} still alive. Force killing...")
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        return True
    except psutil.NoSuchProcess:
        return True
    except Exception as e:
        log("WARNING", f"Could not stop process PID {pid}: {e}")
        return False


def scavenge_ports(ports: List[int]) -> None:
    """Kill any processes occupying the given ports."""
    for port in ports:
        pids = get_pids_on_port(port)
        if pids:
            log("WARNING", f"Port {port} occupied by PIDs {pids}. Cleaning up...")
            for pid in pids:
                kill_process_tree(pid)
        else:
            log("INFO", f"Port {port} is clear.")

def _spawn_litellm(litellm_port: int) -> subprocess.Popen:
    """Spawn the LiteLLM proxy and wait for readiness."""
    log("INFO", f"Spawning LiteLLM Proxy on port {litellm_port}...")
    venv_litellm = os.path.join(ROOT_DIR, ".venv", "Scripts", "litellm.exe")
    if os.path.exists(venv_litellm):
        litellm_args = [venv_litellm, "--config", LITELLM_CONFIG_PATH, "--port", str(litellm_port)]
    else:
        python_exe = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = "python"
        litellm_args = [python_exe, "-m", "litellm", "--config", LITELLM_CONFIG_PATH, "--port", str(litellm_port)]

    # Popen duplicates the handle into the child, so the parent's file object
    # is always closed here — repeated start/stop cycles must not leak fds.
    with open(os.path.join(LOGS_DIR, "system.log"), "a", encoding="utf-8") as sys_log:
        try:
            litellm_flags = 0x00000008 | 0x00000200 | 0x01000000 if platform.system() == "Windows" else 0
            litellm_proc = subprocess.Popen(
                litellm_args, stdout=sys_log, stderr=sys_log,
                creationflags=litellm_flags, close_fds=True,
            )
        except Exception as e:
            log("ERROR", f"Failed to spawn LiteLLM daemon: {e}")
            raise RuntimeError("LiteLLM daemon failed to spawn.")

    log("INFO", "Polling LiteLLM Proxy readiness...")
    ready = False
    for _ in range(30):
        if litellm_proc.poll() is not None:
            log("ERROR", f"LiteLLM daemon exited prematurely with code {litellm_proc.returncode}")
            raise RuntimeError("LiteLLM daemon crashed during startup.")
        try:
            req = urllib.request.Request(f"http://localhost:{litellm_port}/health/readiness")
            with urllib.request.urlopen(req, timeout=1.0) as res:
                if "healthy" in res.read().decode().lower():
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(1)

    if ready:
        log("SUCCESS", "LiteLLM Proxy is online.")
    else:
        log("WARNING", "LiteLLM Proxy is taking longer than expected to launch.")
    return litellm_proc


def _spawn_openclaw(openclaw_port: int, discovery: Any, litellm_pid: int) -> subprocess.Popen:
    """Spawn the OpenClaw gateway and wait for readiness."""
    log("INFO", f"Spawning OpenClaw Gateway on port {openclaw_port}...")
    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    node_exe: str = sys_details["tools"].get("node", "node.exe")

    local_dist = os.path.join(ROOT_DIR, "node_modules", "openclaw", "dist", "index.js")
    global_appdata_dist = os.path.join(
        os.environ.get("AppData", ""), "npm", "node_modules", "openclaw", "dist", "index.js",
    )

    if os.path.exists(local_dist):
        openclaw_exe = node_exe
        openclaw_cmd_args = [local_dist, "gateway", "--port", str(openclaw_port)]
    elif os.path.exists(global_appdata_dist):
        openclaw_exe = node_exe
        openclaw_cmd_args = [global_appdata_dist, "gateway", "--port", str(openclaw_port)]
    else:
        openclaw_exe = "cmd.exe"
        openclaw_cmd_args = ["/c", "openclaw", "gateway", "--port", str(openclaw_port)]

    # Same handle discipline as _spawn_litellm: child inherits, parent closes.
    with open(os.path.join(LOGS_DIR, "system.log"), "a", encoding="utf-8") as sys_log:
        try:
            openclaw_flags = 0x00000008 | 0x00000200 | 0x01000000 if platform.system() == "Windows" else 0
            openclaw_proc = subprocess.Popen(
                [openclaw_exe] + openclaw_cmd_args,
                stdout=sys_log, stderr=sys_log,
                creationflags=openclaw_flags, close_fds=True,
            )
        except Exception as e:
            log("ERROR", f"Failed to spawn OpenClaw daemon: {e}")
            kill_process_tree(litellm_pid)
            raise RuntimeError("OpenClaw daemon failed to spawn.")

    log("INFO", "Polling OpenClaw Gateway readiness...")
    oc_ready = False
    for _ in range(10):
        if openclaw_proc.poll() is not None:
            log("ERROR", f"OpenClaw daemon exited prematurely with code {openclaw_proc.returncode}")
            kill_process_tree(litellm_pid)
            raise RuntimeError("OpenClaw daemon crashed during startup.")
        if get_pids_on_port(openclaw_port):
            oc_ready = True
            break
        time.sleep(1)
    if oc_ready:
        log("SUCCESS", "OpenClaw Gateway is online.")
    else:
        log("WARNING", "OpenClaw Gateway is taking longer than expected to launch.")
    return openclaw_proc


def _check_port_conflicts(settings: Dict[str, Any], litellm_port: int, openclaw_port: int) -> None:
    if settings.get("lifecycle", {}).get("auto_cleanup_ports", True):
        scavenge_ports([litellm_port, openclaw_port])
    else:
        conflicts = []
        if get_pids_on_port(litellm_port):
            conflicts.append(litellm_port)
        if get_pids_on_port(openclaw_port):
            conflicts.append(openclaw_port)
        if conflicts:
            log("ERROR", f"Port collisions detected on {conflicts} and auto_cleanup_ports is False.")
            raise RuntimeError(f"Port collision detected on {conflicts}.")

def _run_vram_profiling(settings: Dict[str, Any], discovery: Any) -> None:
    if settings.get("ollama", {}).get("enabled", False) and settings.get("ollama", {}).get("autostart", False):
        log("INFO", "Performing Pre-flight VRAM Availability Profiling...")
        try:
            sys_details = discovery.run_all_discovery(SETTINGS_PATH)
            ollama_models = sys_details.get("ollama", {}).get("models", [])
            insufficient = [m for m in ollama_models if m.get("status") == "failed"]
            if insufficient:
                names = ", ".join([m["name"] for m in insufficient])
                log("WARNING", f"VRAM Profiling: The following local models exceed system memory capacity and may crash: {names}")
        except Exception as e:
            log("WARNING", f"Pre-flight VRAM Profiling failed: {e}")

def cmd_start() -> None:
    """Start LiteLLM and OpenClaw daemon processes."""
    log("INFO", "Starting AIRM system stack daemons...")

    from . import discovery

    settings = load_yaml(SETTINGS_PATH)
    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    openclaw_port: int = settings.get("openclaw", {}).get("port", 18789)
    litellm_key: str = settings.get("litellm", {}).get("api_key", "sk-litellm-key")

    _check_port_conflicts(settings, litellm_port, openclaw_port)
    _run_vram_profiling(settings, discovery)

    # Setup process env for configuration injection
    os.environ["OPENCLAW_GATEWAY_PORT"] = str(openclaw_port)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"

    providers = load_yaml(PROVIDERS_PATH)
    for _p_name, p_info in providers.items():
        if isinstance(p_info, dict) and p_info.get("enabled", False):
            var = p_info.get("env_var")
            if isinstance(var, str):
                val = get_windows_env(var)
                if val:
                    os.environ[var] = val

    cmd_configure()

    # Reload settings after cmd_configure to pick up rotated litellm key
    settings = load_yaml(SETTINGS_PATH)
    litellm_key = settings.get("litellm", {}).get("api_key", "sk-litellm-key")
    os.environ["LITELLM_API_KEY"] = litellm_key

    litellm_proc = _spawn_litellm(litellm_port)
    openclaw_proc = _spawn_openclaw(openclaw_port, discovery, litellm_proc.pid)

    save_services_state({"litellm": litellm_proc.pid, "openclaw": openclaw_proc.pid})
    log("SUCCESS", f"Daemons initialized. PIDs: LiteLLM={litellm_proc.pid}, OpenClaw={openclaw_proc.pid}")


def cmd_stop() -> None:
    """Terminate all active daemon processes."""
    log("INFO", "Terminating active daemon processes...")
    state = load_services_state()

    if state.get("litellm"):
        kill_process_tree(state["litellm"])
    if state.get("openclaw"):
        kill_process_tree(state["openclaw"])

    settings = load_yaml(SETTINGS_PATH)
    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    openclaw_port: int = settings.get("openclaw", {}).get("port", 18789)
    scavenge_ports([litellm_port, openclaw_port])

    save_services_state({"litellm": None, "openclaw": None})
    log("SUCCESS", "All services stopped.")


def litellm_ready(port: int, timeout: float = 2.0) -> bool:
    """Probe the LiteLLM readiness endpoint (deeper signal than a port check)."""
    try:
        req = urllib.request.Request(f"http://localhost:{port}/health/readiness")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return "healthy" in res.read().decode().lower()
    except Exception:
        return False


def cmd_status() -> Dict[str, Any]:
    """Report the runtime state of daemon processes."""
    log("INFO", "Inspecting runtime state...")
    state = load_services_state()
    settings = load_yaml(SETTINGS_PATH)
    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    openclaw_port: int = settings.get("openclaw", {}).get("port", 18789)

    l_pid = state.get("litellm")
    c_pid = state.get("openclaw")
    l_alive = is_pid_running(l_pid) if l_pid else False
    c_alive = is_pid_running(c_pid) if c_pid else False

    l_pids_on_port = get_pids_on_port(litellm_port)
    c_pids_on_port = get_pids_on_port(openclaw_port)

    l_status = "ONLINE" if (l_alive or l_pids_on_port) else "OFFLINE"
    c_status = "ONLINE" if (c_alive or c_pids_on_port) else "OFFLINE"
    # A listening port can still hide a wedged proxy — probe the HTTP endpoint
    l_ready = litellm_ready(litellm_port) if l_status == "ONLINE" else False

    print("\n==============================================")
    print("      AIRM Server Daemon Status Dashboard")
    print("==============================================")

    if l_status == 'ONLINE':
        l_ready_str = 'HEALTHY' if l_ready else 'UNRESPONSIVE'
    else:
        l_ready_str = 'N/A'

    print(f"LiteLLM Proxy (Port {litellm_port}):     {l_status} (PID: {l_pid or 'N/A'}, Active on Port: {l_pids_on_port}, Readiness: {l_ready_str})")
    print(f"OpenClaw Gateway (Port {openclaw_port}):  {c_status} (PID: {c_pid or 'N/A'}, Active on Port: {c_pids_on_port})")
    print("==============================================")

    return {
        "litellm": {"status": l_status, "pid": l_pid, "pids_on_port": l_pids_on_port, "ready": l_ready},
        "openclaw": {"status": c_status, "pid": c_pid, "pids_on_port": c_pids_on_port},
    }


def _stack_health() -> Dict[str, bool]:
    """Liveness of each daemon: tracked PID alive or something listening on its port."""
    settings = load_yaml(SETTINGS_PATH)
    state = load_services_state()
    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    openclaw_port: int = settings.get("openclaw", {}).get("port", 18789)
    return {
        "litellm": is_pid_running(state.get("litellm")) or bool(get_pids_on_port(litellm_port)),
        "openclaw": is_pid_running(state.get("openclaw")) or bool(get_pids_on_port(openclaw_port)),
    }


def check_and_heal() -> bool:
    """One watchdog pass. Returns True when the stack is (or was restored to) healthy.

    Restarts the whole stack rather than a single daemon: OpenClaw depends on
    LiteLLM and cmd_start already handles ordering, port scavenging, and config
    recompilation.
    """
    health = _stack_health()
    if all(health.values()):
        return True
    down = ", ".join(name for name, ok in health.items() if not ok)
    log("WARNING", f"Watchdog: {down} offline. Restarting service stack...")
    try:
        cmd_stop()
        cmd_start()
        return all(_stack_health().values())
    except Exception as e:
        log("ERROR", f"Watchdog restart failed: {e}")
        return False


def watch_loop(poll_seconds: int = 15, wait=time.sleep, should_stop=lambda: False) -> None:
    """Core watchdog loop with injectable wait/stop hooks so it can run both
    interactively (cmd_watch) and inside an OS service (core/service.py)."""
    consecutive_failures = 0
    lock = ProcessLock("watchdog")

    if not lock.acquire():
        log("ERROR", "Another watchdog process is already running. Exiting.")
        return

    try:
        while not should_stop():
            if check_and_heal():
                consecutive_failures = 0
                delay = poll_seconds
            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    log("ERROR", "Watchdog halted after 3 consecutive rapid failures to prevent resource exhaustion.")
                    break
                # Exponential backoff, capped at 5 min, so a hard-broken stack
                # is not restart-hammered in a tight loop.
                delay = min(poll_seconds * (2 ** consecutive_failures), 300)
                log("WARNING", f"Watchdog: stack still unhealthy ({consecutive_failures} consecutive failures). Next attempt in {delay}s.")
            wait(delay)
    finally:
        lock.release()


def cmd_watch(poll_seconds: int = 15) -> None:
    """Supervise the daemons and auto-restart them when they die (self-healing loop)."""
    log("INFO", f"AIRM watchdog active (polling every {poll_seconds}s). Press Ctrl+C to stop.")
    try:
        watch_loop(poll_seconds)
    except KeyboardInterrupt:
        log("INFO", "Watchdog stopped by user.")
