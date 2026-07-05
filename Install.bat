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
    
    echo [INFO] Refreshing environment variables...
    for /f "tokens=2*" %%A in ('reg query "HKLM\System\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%B"
    for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USR_PATH=%%B"
    set "PATH=!SYS_PATH!;!USR_PATH!;%LocalAppData%\Programs\Python\Python311\Scripts;%LocalAppData%\Programs\Python\Python311"

    python --version >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo [ERROR] Python 3 not found or unusable. Please install Python 3.10+ manually.
        pause
        exit /b 1
    )
)

:: 2. Run the centralized Python bootstrapper
python "%~dp0core\bootstrap.py"
if errorlevel 1 (
    echo.
    echo ==============================================
    echo              INSTALLATION SUMMARY
    echo ==============================================
    echo [x] Core Prerequisites         : SKIPPED/FAILED
    echo [x] Python Environment         : FAILED
    echo [x] Dependencies               : FAILED
    echo ==============================================
    echo [ERROR] Installation failed. See output above for details.
    pause
    exit /b 1
)

echo.
echo ==============================================
echo              INSTALLATION SUMMARY
echo ==============================================
echo [v] Core Prerequisites         : SUCCESS
echo [v] Python Environment         : SUCCESS
echo [v] Dependencies               : SUCCESS
echo [v] Web Guided Assistant       : SUCCESS
echo ==============================================
echo [SUCCESS] OpenClaw Workstation installation completed successfully.
echo.
echo NEXT STEP: Run 'Start.bat' or 'Manage.bat start' to launch the background services.
echo For advanced options, you can run 'Manage.bat' directly.
echo.
pause
