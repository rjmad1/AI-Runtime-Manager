#!/usr/bin/env bash

echo "=============================================="
echo "       Starting OpenClaw Workstation"
echo "=============================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

if [ ! -f "$SCRIPT_DIR/manage.sh" ]; then
    echo "[ERROR] manage.sh not found. Please ensure you are in the correct directory."
    exit 1
fi

"$SCRIPT_DIR/manage.sh" start
