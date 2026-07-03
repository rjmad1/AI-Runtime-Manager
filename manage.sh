#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [ -z "$1" ]; then
    echo "=============================================="
    echo "     OpenClaw Workstation Lifecycle Manager"
    echo "=============================================="
    echo "Usage:"
    echo "  ./manage.sh start     - Start LiteLLM + OpenClaw servers"
    echo "  ./manage.sh stop      - Force stop all running servers"
    echo "  ./manage.sh status    - Check running components status"
    echo "  ./manage.sh configure - Regenerate configuration files"
    echo "  ./manage.sh diagnose  - Run latency connectivity benchmarks"
    echo "  ./manage.sh repair    - Run self-healing and check prerequisites"
    echo "  ./manage.sh backup    - Create timestamped configuration backup"
    echo "  ./manage.sh restore   - Interactively restore a configuration"
    echo "  ./manage.sh upgrade   - Upgrade python and npm dependencies"
    echo "  ./manage.sh uninstall - Uninstall the stack and clean local files"
    echo "=============================================="
    exit 0
fi

if [ ! -f "$DIR/.venv/bin/python" ]; then
    # Fallback to Scripts/python for git bash on windows
    if [ ! -f "$DIR/.venv/Scripts/python" ] && [ ! -f "$DIR/.venv/Scripts/python.exe" ]; then
        echo "[ERROR] Virtual environment not found. Please run ./install.sh first!"
        exit 1
    fi
    PYTHON_EXE="$DIR/.venv/Scripts/python"
    [ -f "$DIR/.venv/Scripts/python.exe" ] && PYTHON_EXE="$DIR/.venv/Scripts/python.exe"
else
    PYTHON_EXE="$DIR/.venv/bin/python"
fi

"$PYTHON_EXE" "$DIR/core/manager.py" "$@"
