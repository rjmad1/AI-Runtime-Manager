# install.ps1
# Simple powershell bootstrapper for AI-Runtime-Manager.

$ErrorActionPreference = "Stop"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "      OpenClaw Workstation Bootstrapper" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$venvDir = Join-Path $scriptDir ".venv"

# 1. Detect Python
$pythonPath = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if (-not $pythonPath -and (Test-Path "C:\Python314\python.exe")) {
    $pythonPath = "C:\Python314\python.exe"
} elseif (-not $pythonPath -and (Test-Path "$env:LocalAppData\Programs\Python\Python311\python.exe")) {
    $pythonPath = "$env:LocalAppData\Programs\Python\Python311\python.exe"
}

if (-not $pythonPath) {
    Write-Host "[INFO] Python not found. Attempting to install Python 3.11 via winget..." -ForegroundColor Yellow
    try {
        Start-Process winget -ArgumentList "install --silent --accept-source-agreements --accept-package-agreements Python.Python.3.11" -NoNewWindow -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $pythonPath = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
    } catch {
        Write-Host "[ERROR] Failed to install Python." -ForegroundColor Red
        Exit 1
    }
}
if (-not $pythonPath) {
    Write-Host "[ERROR] Python 3 not found. Please install Python 3.10+ manually." -ForegroundColor Red
    Exit 1
}

Write-Host "[INFO] Using python: $pythonPath" -ForegroundColor Cyan

# 2. Run Centralized Python Bootstrapper
$bootstrapScript = Join-Path $scriptDir "core\bootstrap.py"
& $pythonPath $bootstrapScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Python bootstrap failed." -ForegroundColor Red
    Exit 1
}

# 3. Launch Manager
Write-Host "[INFO] Launching Web Guided Assistant..." -ForegroundColor Cyan
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (Test-Path $venvPython) {
    Set-Location $scriptDir
    & $venvPython -m core.manager install
} else {
    Write-Host "[ERROR] Virtual environment python was not found after bootstrap setup!" -ForegroundColor Red
    Exit 1
}
