@echo off
setlocal

if "%~1"=="" (
    echo ==============================================
    echo      OpenClaw Workstation Lifecycle Manager
    echo ==============================================
    echo Usage:
    echo   Manage.bat start     - Start LiteLLM + OpenClaw servers
    echo   Manage.bat stop      - Force stop all running servers
    echo   Manage.bat status    - Check running components status
    echo   Manage.bat watch     - Self-healing watchdog: auto-restart crashed daemons
    echo   Manage.bat service   - OS service control: install^|uninstall^|start^|stop^|status
    echo   Manage.bat secret    - Credential store: list^|set^|rotate^|delete ^<ENV_VAR^>
    echo   Manage.bat user      - Control-plane users: list^|add^|remove ^<name^>
    echo   Manage.bat apikey    - Scoped API keys: list^|create^|revoke ^<name^>
    echo   Manage.bat migrate   - Schema migrations: apply^|status^|rollback ^<version^>
    echo   Manage.bat history   - Config versioning: list^|diff^|rollback^|tag ^<id^>
    echo   Manage.bat configure - Regenerate configuration files
    echo   Manage.bat diagnose  - Run latency connectivity benchmarks
    echo   Manage.bat inventory - Generate enterprise dependency inventory report
    echo   Manage.bat repair    - Run self-healing and check prerequisites
    echo   Manage.bat backup    - Create timestamped configuration backup
    echo   Manage.bat restore   - Interactively restore a configuration
    echo   Manage.bat upgrade   - Upgrade python and npm dependencies
    echo   Manage.bat uninstall - Uninstall the stack and clean local files
    echo ==============================================
    exit /b 0
)

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run Install.bat first!
    exit /b 1
)

pushd "%~dp0"
".venv\Scripts\python.exe" -m core.manager %*
popd
