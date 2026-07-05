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

# 2. Run Centralized Python Bootstrapper
$PYTHON_CMD "$DIR/core/bootstrap.py"
