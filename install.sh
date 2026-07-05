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
if $PYTHON_CMD "$DIR/core/bootstrap.py"; then
    echo ""
    echo "=============================================="
    echo "             INSTALLATION SUMMARY"
    echo "=============================================="
    echo "[v] Core Prerequisites         : SUCCESS"
    echo "[v] Python Environment         : SUCCESS"
    echo "[v] Dependencies               : SUCCESS"
    echo "[v] Web Guided Assistant       : SUCCESS"
    echo "=============================================="
    echo "[SUCCESS] OpenClaw Workstation installation completed successfully."
    echo "You can manage your servers using ./manage.sh"
    echo ""
else
    echo ""
    echo "=============================================="
    echo "             INSTALLATION SUMMARY"
    echo "=============================================="
    echo "[x] Core Prerequisites         : SKIPPED/FAILED"
    echo "[x] Python Environment         : FAILED"
    echo "[x] Dependencies               : FAILED"
    echo "=============================================="
    echo "[ERROR] Python bootstrap failed. Installation aborted."
    exit 1
fi
