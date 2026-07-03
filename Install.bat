@echo off
setlocal enabledelayedexpansion

echo ==============================================
echo       OpenClaw Workstation Installer
echo ==============================================

:: 1. Run low-level bootstrap powershell script
powershell -ExecutionPolicy Bypass -File "%~dp0core\bootstrap.ps1"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Low-level bootstrap failed. Exiting.
    pause
    exit /b 1
)

:: 2. Run the Python interactive installer in the .venv
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0core\manager.py" install
) else (
    echo [ERROR] Virtual environment python was not found after bootstrap!
    pause
    exit /b 1
)

echo.
echo [SUCCESS] OpenClaw Workstation installation completed successfully.
echo You can manage your servers using Manage.bat.
echo.
pause
