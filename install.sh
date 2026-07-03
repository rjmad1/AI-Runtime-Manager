#!/usr/bin/env bash
# install.sh
# Simple bash bootstrapper for AI-Runtime-Manager (OpenClaw Workstation).

set -e

echo "=============================================="
echo "      OpenClaw Workstation Bootstrapper"
echo "=============================================="

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$DIR/.venv"

# 1. Detect Python
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python 3 not found. Please install Python 3.10+ manually."
    exit 1
fi

echo "[INFO] Using python: $($PYTHON_CMD --version)"

# 2. Detect Node.js
if ! command -v node &>/dev/null; then
    echo "[ERROR] Node.js not found. Please install Node.js LTS manually."
    exit 1
fi
echo "[INFO] Using node: $(node --version)"

# 3. Detect uv or pip
if command -v uv &>/dev/null; then
    PIP_CMD="uv pip"
    VENV_CMD="uv venv"
else
    echo "[WARN] uv not found, falling back to built-in venv/pip."
    PIP_CMD="$PYTHON_CMD -m pip"
    VENV_CMD="$PYTHON_CMD -m venv"
fi

# 4. Create venv
if [ -d "$VENV_DIR" ]; then
    echo "[INFO] Virtual environment already exists at $VENV_DIR."
else
    echo "[INFO] Creating virtual environment..."
    $VENV_CMD "$VENV_DIR"
fi

# 5. Install Python Dependencies
echo "[INFO] Installing python dependencies..."
if [ -f "$VENV_DIR/bin/pip" ]; then
    VENV_PIP="$VENV_DIR/bin/pip"
    VENV_PYTHON="$VENV_DIR/bin/python"
else
    VENV_PIP="$VENV_DIR/Scripts/pip" # fallback for cygwin/msys
    VENV_PYTHON="$VENV_DIR/Scripts/python"
    [ -f "$VENV_DIR/Scripts/python.exe" ] && VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
fi

# Install pinned dependencies from the single source of truth
if command -v uv &>/dev/null; then
    uv pip install --python "$VENV_PYTHON" -r "$DIR/requirements.txt"
else
    "$VENV_PIP" install -r "$DIR/requirements.txt"
fi

# 6. Install OpenClaw
if [ -f "$DIR/node_modules/openclaw/dist/index.js" ]; then
    echo "[INFO] Local OpenClaw installation detected."
elif command -v openclaw &>/dev/null; then
    echo "[INFO] Global OpenClaw installation detected."
else
    echo "[INFO] Installing OpenClaw locally..."
    cd "$DIR"
    npm install openclaw
fi

echo "[SUCCESS] Bootstrap phase completed successfully."

# 7. Launch Manager
echo "[INFO] Launching Web Guided Assistant..."
if [ -f "$VENV_PYTHON" ]; then
    cd "$DIR" && "$VENV_PYTHON" -m core.manager install
else
    echo "[ERROR] Virtual environment python was not found after bootstrap setup!"
    exit 1
fi
