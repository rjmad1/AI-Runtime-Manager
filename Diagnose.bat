@echo off
setlocal

echo ==============================================
echo       OpenClaw Workstation Diagnostics
echo ==============================================

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run Install.bat first!
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0core\manager.py" diagnose

if %ERRORLEVEL% eq 0 (
    echo [INFO] Opening visual health report in default browser...
    if exist "%~dp0generated\health-report.html" (
        start "" "%~dp0generated\health-report.html"
    )
)
