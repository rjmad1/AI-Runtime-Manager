# core/bootstrap.py
# Platform-agnostic environment bootstrap script.
# Assumes Python 3.10+ is already installed.

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


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

def ensure_node():
    if shutil.which("node"):
        log_success("Node.js detected.")
        return True

    log_warn("Node.js not detected.")
    if platform.system() == "Windows":
        log_info("Attempting to install Node.js via winget...")
        if run_cmd(["winget", "install", "--silent", "--accept-source-agreements", "--accept-package-agreements", "OpenJS.NodeJS.LTS"]):
            log_success("Node.js installed. Note: You may need to restart your terminal after bootstrap completes.")
            return True
        else:
            log_error("Failed to install Node.js via winget.")

    log_error("Please install Node.js manually and ensure 'node' is in your PATH.")
    sys.exit(1)

def ensure_git():
    if shutil.which("git"):
        log_success("Git detected.")
        return True

    log_warn("Git not detected.")
    if platform.system() == "Windows":
        log_info("Attempting to install Git via winget...")
        if run_cmd(["winget", "install", "--silent", "--accept-source-agreements", "--accept-package-agreements", "Git.Git"]):
            log_success("Git installed.")
            return True
    log_warn("Git is highly recommended. Please install it manually.")
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
            run_cmd([uv_path, "venv", str(venv_dir)])
        else:
            log_info("uv not found, using standard venv...")
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

    if uv_path:
        run_cmd([uv_path, "pip", "install", "--python", venv_python, "-r", str(req_file)])
    else:
        run_cmd([venv_python, "-m", "pip", "install", "-r", str(req_file)])
    log_success("Python dependencies installed.")

def install_openclaw(root_dir: Path):
    if (root_dir / "node_modules" / "openclaw" / "dist" / "index.js").exists():
        log_success("Local OpenClaw installation detected.")
        return

    if shutil.which("openclaw"):
        log_success("Global OpenClaw installation detected.")
        return

    log_info("Installing OpenClaw via npm...")
    if run_cmd(["npm", "install", "-g", "openclaw"]):
        log_success("OpenClaw installed globally.")
    else:
        log_warn("Global install failed. Attempting local install...")
        if run_cmd(["npm", "install", "openclaw"], cwd=str(root_dir)):
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
        run_cmd([sys.executable, "-m", "pip", "install", "uv", "--user"])

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
    
    # 6. Launch Web Guided Assistant
    log_info("Launching Web Guided Assistant...")
    venv_python = get_venv_python(venv_dir)
    try:
        subprocess.check_call([venv_python, "-m", "core.manager", "install"], cwd=str(root_dir))
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to launch Web Guided Assistant: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
