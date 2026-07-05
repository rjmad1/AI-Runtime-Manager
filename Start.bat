@echo off
setlocal

echo ==============================================
echo        Starting OpenClaw Workstation
echo ==============================================

if not exist "%~dp0Manage.bat" (
    echo [ERROR] Manage.bat not found. Please ensure you are in the correct directory.
    pause
    exit /b 1
)

call "%~dp0Manage.bat" start

echo.
pause
