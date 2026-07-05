# install.ps1
# Simple powershell bootstrapper for AI-Runtime-Manager.

$ErrorActionPreference = "Stop"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "      OpenClaw Workstation Bootstrapper" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

$scriptDir = $PSScriptRoot

if (-not $scriptDir) {
    # Script was run via iex (in-memory)
    $scriptDir = $PWD.Path
}

# Prevent installing directly into System32
if ($scriptDir -match "System32") {
    $scriptDir = $env:USERPROFILE
    Set-Location $scriptDir
    Write-Host "[INFO] Redirecting install from System32 to $scriptDir" -ForegroundColor Cyan
}

# If the core script doesn't exist here, we need to clone the repository
if (-not (Test-Path (Join-Path $scriptDir "core\bootstrap.py"))) {
    Write-Host "[INFO] Repository not found locally. Cloning from GitHub..." -ForegroundColor Cyan
    $repoDir = Join-Path $scriptDir "AI-Runtime-Manager"
    
    if (-not (Test-Path (Join-Path $repoDir "core\bootstrap.py"))) {
        # Check if Git is installed and usable
        $gitUsable = $false
        $gitPath = Get-Command git -ErrorAction SilentlyContinue
        if ($gitPath) {
            try {
                $gitVer = git --version 2>&1
                if ($gitVer -match "git version") { $gitUsable = $true }
            } catch {}
        }

        if (-not $gitUsable) {
            Write-Host "[INFO] Git not found or unusable. Attempting to install Git via winget..." -ForegroundColor Yellow
            try {
                Start-Process winget -ArgumentList "install --silent --accept-source-agreements --accept-package-agreements Git.Git" -NoNewWindow -Wait
                $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
                try {
                    $gitVer = git --version 2>&1
                    if ($gitVer -match "git version") { $gitUsable = $true }
                } catch {}
            } catch {
                Write-Host "[ERROR] Failed to install Git." -ForegroundColor Red
                Exit 1
            }
            if (-not $gitUsable) {
                Write-Host "[ERROR] Git is required to clone the repository. Please install Git manually." -ForegroundColor Red
                Exit 1
            }
        }

        git clone https://github.com/rjmad1/AI-Runtime-Manager.git $repoDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to clone repository." -ForegroundColor Red
            Exit 1
        }
    }
    $scriptDir = $repoDir
    Set-Location $scriptDir
}
# 1. Detect Python
$pythonPath = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if (-not $pythonPath -and (Test-Path "C:\Python314\python.exe")) {
    $pythonPath = "C:\Python314\python.exe"
} elseif (-not $pythonPath -and (Test-Path "$env:LocalAppData\Programs\Python\Python311\python.exe")) {
    $pythonPath = "$env:LocalAppData\Programs\Python\Python311\python.exe"
}

$pythonUsable = $false
if ($pythonPath) {
    try {
        $pyVer = & $pythonPath --version 2>&1
        if ($pyVer -match "Python") { $pythonUsable = $true }
    } catch {}
}

if (-not $pythonUsable) {
    Write-Host "[INFO] Python not found or unusable. Attempting to install Python 3.11 via winget..." -ForegroundColor Yellow
    try {
        Start-Process winget -ArgumentList "install --silent --accept-source-agreements --accept-package-agreements Python.Python.3.11" -NoNewWindow -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $pythonPath = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
        if ($pythonPath) {
            try {
                $pyVer = & $pythonPath --version 2>&1
                if ($pyVer -match "Python") { $pythonUsable = $true }
            } catch {}
        }
    } catch {
        Write-Host "[ERROR] Failed to install Python." -ForegroundColor Red
        Exit 1
    }
}
if (-not $pythonUsable) {
    Write-Host "[ERROR] Python 3 not found or unusable. Please install Python 3.10+ manually." -ForegroundColor Red
    Exit 1
}

Write-Host "[INFO] Using python: $pythonPath" -ForegroundColor Cyan

# 2. Run Centralized Python Bootstrapper
$bootstrapScript = Join-Path $scriptDir "core\bootstrap.py"
& $pythonPath $bootstrapScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n==============================================" -ForegroundColor Red
    Write-Host "             INSTALLATION SUMMARY" -ForegroundColor Red
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host "[x] Core Prerequisites         : SKIPPED/FAILED" -ForegroundColor Red
    Write-Host "[x] Python Environment         : FAILED" -ForegroundColor Red
    Write-Host "[x] Dependencies               : FAILED" -ForegroundColor Red
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host "[ERROR] Python bootstrap failed. Installation aborted." -ForegroundColor Red
    Exit 1
}

Write-Host "`n==============================================" -ForegroundColor Green
Write-Host "             INSTALLATION SUMMARY" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host "[v] Core Prerequisites         : SUCCESS" -ForegroundColor Green
Write-Host "[v] Python Environment         : SUCCESS" -ForegroundColor Green
Write-Host "[v] Dependencies               : SUCCESS" -ForegroundColor Green
Write-Host "[v] Web Guided Assistant       : SUCCESS" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host "[SUCCESS] OpenClaw Workstation installation completed successfully." -ForegroundColor Green
Write-Host ""
Write-Host "NEXT STEP: Run '.\Start.bat' or '.\Manage.bat start' to launch the background services." -ForegroundColor Cyan
Write-Host "For advanced options, run '.\Manage.bat' directly." -ForegroundColor Cyan
Write-Host ""
