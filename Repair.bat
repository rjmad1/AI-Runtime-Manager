@echo off
setlocal

echo ==============================================
echo       OpenClaw Workstation Self-Healing
echo ==============================================

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run Install.bat first!
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0core\manager.py" repair
pause
