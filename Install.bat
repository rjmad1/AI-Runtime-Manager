@echo off
setlocal enabledelayedexpansion

echo ==============================================
echo       OpenClaw Workstation Installer
echo ==============================================

:: 1. Ensure Python 3 is available
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Python not found. Attempting to install Python 3.11 via winget...
    winget install --silent --accept-source-agreements --accept-package-agreements Python.Python.3.11
    set "PATH=%PATH%;%LocalAppData%\Programs\Python\Python311"
)

:: 2. Run the centralized Python bootstrapper
python "%~dp0core\bootstrap.py"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python bootstrap failed. Exiting.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] OpenClaw Workstation installation completed successfully.
echo You can manage your servers using Manage.bat.
echo.
pause
