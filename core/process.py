# core/process.py
# Process lifecycle, port management, and service daemon control for AIRM.

import os
import sys
import re
import json
import time
import platform
import subprocess
import urllib.request
import psutil
from typing import Any, Dict, List, Optional

from config import (
    CORE_DIR, ROOT_DIR, LOGS_DIR,
    SETTINGS_PATH, PROVIDERS_PATH,
    LITELLM_CONFIG_PATH, SERVICES_STATE_PATH,
    log, load_yaml, get_windows_env, cmd_configure,
)


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
            if conn.laddr.port == port and conn.status == 'LISTEN':
                if conn.pid is not None:
                    pids.add(conn.pid)
        return list(pids)
    except psutil.AccessDenied:
        pass
    except Exception as e:
        log("WARNING", f"Could not list TCP connections via psutil: {e}")

    # Fallback for Windows without elevation
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
        
        gone, alive = psutil.wait_procs(children + [parent], timeout=3)
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

    litellm_log = open(os.path.join(LOGS_DIR, "litellm.log"), "w", encoding="utf-8")
    try:
        litellm_flags = 0x00000008 | 0x00000200 | 0x01000000 if platform.system() == "Windows" else 0
        litellm_proc = subprocess.Popen(
            litellm_args, stdout=litellm_log, stderr=litellm_log,
            creationflags=litellm_flags, close_fds=True,
        )
    except Exception as e:
        litellm_log.close()
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

    openclaw_log = open(os.path.join(LOGS_DIR, "openclaw.log"), "w", encoding="utf-8")
    try:
        openclaw_flags = 0x00000008 | 0x00000200 | 0x01000000 if platform.system() == "Windows" else 0
        openclaw_proc = subprocess.Popen(
            [openclaw_exe] + openclaw_cmd_args,
            stdout=openclaw_log, stderr=openclaw_log,
            creationflags=openclaw_flags, close_fds=True,
        )
    except Exception as e:
        openclaw_log.close()
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


def cmd_start() -> None:
    """Start LiteLLM and OpenClaw daemon processes."""
    log("INFO", "Starting AIRM system stack daemons...")

    try:
        import discovery
    except ImportError:
        sys.path.append(CORE_DIR)
        import discovery

    settings = load_yaml(SETTINGS_PATH)
    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    openclaw_port: int = settings.get("openclaw", {}).get("port", 18789)
    litellm_key: str = settings.get("litellm", {}).get("api_key", "sk-litellm-key")

    if settings.get("lifecycle", {}).get("auto_cleanup_ports", True):
        scavenge_ports([litellm_port, openclaw_port])

    # Setup process env for configuration injection
    os.environ["OPENCLAW_GATEWAY_PORT"] = str(openclaw_port)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"

    providers = load_yaml(PROVIDERS_PATH)
    for _p_name, p_info in providers.items():
        if isinstance(p_info, dict) and p_info.get("enabled", False):
            var = p_info.get("env_var")
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

    print("\n==============================================")
    print("      AIRM Server Daemon Status Dashboard")
    print("==============================================")
    print(f"LiteLLM Proxy (Port {litellm_port}):     {l_status} (PID: {l_pid or 'N/A'}, Active on Port: {l_pids_on_port})")
    print(f"OpenClaw Gateway (Port {openclaw_port}):  {c_status} (PID: {c_pid or 'N/A'}, Active on Port: {c_pids_on_port})")
    print("==============================================")

    return {
        "litellm": {"status": l_status, "pid": l_pid, "pids_on_port": l_pids_on_port},
        "openclaw": {"status": c_status, "pid": c_pid, "pids_on_port": c_pids_on_port},
    }
