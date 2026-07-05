# core/bootstrap.py
# Platform-agnostic environment bootstrap script.
# Assumes Python 3.10+ is already installed.

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

if platform.system() == 'Windows':
    import winreg


def log_info(msg):
    print(f"\033[36m[INFO]\033[0m {msg}")

def log_success(msg):
    print(f"\033[32m[SUCCESS]\033[0m {msg}")

def log_warn(msg):
    print(f"\033[33m[WARNING]\033[0m {msg}")

def log_error(msg):
    print(f"\033[31m[ERROR]\033[0m {msg}")

# ANSI colors fallback for windows cmd
if platform.system() == "Windows":
    subprocess.run('color', shell=True, check=False)

def run_cmd(cmd, cwd=None, capture=False):
    try:
        if capture:
            return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.STDOUT)
        else:
            subprocess.check_call(cmd, cwd=cwd)
            return True
    except subprocess.CalledProcessError as e:
        if capture:
            return e.output
        return False
    except FileNotFoundError:
        return False

def refresh_windows_path():
    if platform.system() != "Windows":
        return
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"System\CurrentControlSet\Control\Session Manager\Environment") as key:
            sys_path = winreg.QueryValueEx(key, "Path")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            usr_path = winreg.QueryValueEx(key, "Path")[0]
        os.environ["PATH"] = f"{sys_path};{usr_path}"
        log_info("Environment PATH refreshed from registry.")
    except Exception as e:
        log_warn(f"Failed to refresh PATH from registry: {e}")

def run_cmd_retry(cmd, cwd=None, retries=3):
    import time
    for attempt in range(1, retries + 1):
        if run_cmd(cmd, cwd=cwd):
            return True
        log_warn(f"Command failed (attempt {attempt}/{retries}). Retrying in 2 seconds...")
        time.sleep(2)
    return False

def check_usability(cmd):
    try:
        subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def ensure_node():
    if shutil.which("node") and check_usability(["node", "-v"]):
        log_success("Node.js detected and usable.")
        return True

    log_warn("Node.js not detected or not usable.")
    if platform.system() == "Windows":
        log_info("Attempting to install Node.js via winget...")
        if run_cmd(["winget", "install", "--silent", "--accept-source-agreements", "--accept-package-agreements", "OpenJS.NodeJS.LTS"]):
            refresh_windows_path()
            if shutil.which("node") and check_usability(["node", "-v"]):
                log_success("Node.js installed and verified.")
                return True
            else:
                log_error("Node.js installed but still not usable. You may need to manually add it to PATH.")
        else:
            log_error("Failed to install Node.js via winget.")

    log_error("Please install Node.js manually and ensure 'node' is in your PATH.")
    sys.exit(1)

def ensure_git():
    if shutil.which("git") and check_usability(["git", "--version"]):
        log_success("Git detected and usable.")
        return True

    log_warn("Git not detected or not usable.")
    if platform.system() == "Windows":
        log_info("Attempting to install Git via winget...")
        if run_cmd(["winget", "install", "--silent", "--accept-source-agreements", "--accept-package-agreements", "Git.Git"]):
            refresh_windows_path()
            if shutil.which("git") and check_usability(["git", "--version"]):
                log_success("Git installed and verified.")
                return True
    log_warn("Git is highly recommended but not usable. Please install it manually.")
    return False

def get_uv_path():
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path

    home = Path.home()
    if platform.system() == "Windows":
        local_uv = home / ".local" / "bin" / "uv.exe"
    else:
        local_uv = home / ".local" / "bin" / "uv"

    if local_uv.exists():
        return str(local_uv)
    return None

def setup_venv(root_dir: Path):
    venv_dir = root_dir / ".venv"
    if venv_dir.exists():
        log_info(f"Virtual environment already exists at {venv_dir}")
    else:
        log_info("Creating virtual environment...")
        uv_path = get_uv_path()
        if uv_path:
            if not run_cmd([uv_path, "venv", str(venv_dir)]):
                log_warn("uv venv failed. Falling back to standard venv...")
                uv_path = None

        if not uv_path:
            log_info("using standard venv...")
            run_cmd([sys.executable, "-m", "venv", str(venv_dir)])
        log_success("Virtual environment created.")

    return venv_dir

def get_venv_python(venv_dir: Path):
    if platform.system() == "Windows":
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")

def install_python_deps(root_dir: Path, venv_dir: Path):
    log_info("Installing python dependencies...")
    req_file = root_dir / "requirements.txt"
    venv_python = get_venv_python(venv_dir)
    uv_path = get_uv_path()

    success = False
    if uv_path:
        success = run_cmd_retry([uv_path, "pip", "install", "--python", venv_python, "-r", str(req_file)])

    if not success:
        if uv_path:
            log_warn("uv pip install failed. Falling back to pip...")
        success = run_cmd_retry([venv_python, "-m", "pip", "install", "-r", str(req_file)])

    if not success:
        log_error("Failed to install Python dependencies. Please check your network connection or build tools.")
        sys.exit(1)

    log_success("Python dependencies installed.")

def install_openclaw(root_dir: Path):
    if (root_dir / "node_modules" / "openclaw" / "dist" / "index.js").exists():
        log_success("Local OpenClaw installation detected.")
        return

    if shutil.which("openclaw") and check_usability(["openclaw", "--version"]):
        log_success("Global OpenClaw installation detected.")
        return

    log_info("Installing OpenClaw via npm...")
    if run_cmd_retry(["npm", "install", "-g", "openclaw"]):
        log_success("OpenClaw installed globally.")
    else:
        log_warn("Global install failed. Attempting local install...")
        if run_cmd_retry(["npm", "install", "openclaw"], cwd=str(root_dir)):
            log_success("OpenClaw installed locally.")
        else:
            log_error("Failed to install openclaw. Please install Node/npm and run 'npm install openclaw' manually.")
            sys.exit(1)

def main():
    log_info("==============================================")
    log_info("      OpenClaw Workstation Bootstrapper       ")
    log_info("==============================================")

    root_dir = Path(__file__).resolve().parent.parent

    # 1. Ensure UV is available
    if not get_uv_path():
        log_info("Installing uv via pip...")
        run_cmd_retry([sys.executable, "-m", "pip", "install", "uv", "--user"])

    # 2. System dependencies
    ensure_git()
    ensure_node()

    # 3. Virtual Environment
    venv_dir = setup_venv(root_dir)

    # 4. Python Dependencies
    install_python_deps(root_dir, venv_dir)

    # 5. OpenClaw node package
    install_openclaw(root_dir)

    log_success("Bootstrap phase completed successfully.")

    venv_python = get_venv_python(venv_dir)

    # Pre-flight validation
    log_info("Validating dependencies before launch...")
    try:
        subprocess.check_call([venv_python, "-c", "import psutil, requests, yaml, litellm"], cwd=str(root_dir))
        log_success("Dependencies validated successfully.")
    except subprocess.CalledProcessError:
        log_error("Dependency validation failed. Some required packages are missing.")
        sys.exit(1)

    # 6. Launch Web Guided Assistant
    log_info("Launching Web Guided Assistant...")
    try:
        subprocess.check_call([venv_python, "-m", "core.manager", "install"], cwd=str(root_dir))
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to launch Web Guided Assistant: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
