# install.ps1
# Single-line PowerShell bootstrapper installer for AI-Runtime-Manager (OpenClaw Workstation).
# Execution command:
# powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 | iex"

$ErrorActionPreference = "Stop"

function Log-Info ($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Log-Success ($msg) { Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Log-Warn ($msg) { Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Log-Error ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Clear-Host
Log-Info "=========================================================="
Log-Info "    OpenClaw Workstation AI Runtime Manager (AIRM)"
Log-Info "=========================================================="
Log-Info "Initializing zero-touch background installer..."

# 1. Resolve Installation Directory
$targetDir = Join-Path $Home "AI-Runtime-Manager"
Log-Info "Target installation path resolved to: $targetDir"

if (Test-Path $targetDir) {
    Log-Warn "An existing installation was found at $targetDir."
    $choice = Read-Host "Would you like to overwrite it and perform a fresh install? (y/n)"
    if ($choice.ToLower().Trim() -eq 'y' -or $choice.ToLower().Trim() -eq 'yes') {
        Log-Info "Cleaning up old installation..."
        try {
            $pids = @()
            Get-NetTCPConnection -LocalPort 4000, 18789 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
                $pids += $_.OwningProcess
            }
            if ($pids.Count -gt 0) {
                Log-Info "Stopping active servers on ports 4000/18789..."
                Stop-Process -Id $pids -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item $targetDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Log-Info "Installation cancelled by user."
        Exit 0
    }
}

# 2. Retrieve codebase
$repoUrl = "https://github.com/rjmad1/AI-Runtime-Manager.git"
$zipUrl = "https://github.com/rjmad1/AI-Runtime-Manager/archive/refs/heads/main.zip"
$tempZip = Join-Path $env:TEMP "AI-Runtime-Manager.zip"
$tempExtract = Join-Path $env:TEMP "AI-Runtime-Manager-extract"

Log-Info "Retrieving latest release packages from GitHub..."
$retrievalSuccess = $false

$gitPath = Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if ($gitPath) {
    Log-Info "Git detected. Cloning repository..."
    try {
        if (Test-Path $targetDir) { Remove-Item $targetDir -Recurse -Force -ErrorAction SilentlyContinue }
        Start-Process git -ArgumentList "clone $repoUrl `"$targetDir`"" -NoNewWindow -Wait -ErrorAction Stop
        if (Test-Path (Join-Path $targetDir "core\bootstrap.ps1")) {
            Log-Success "Repository cloned successfully via Git to: $targetDir"
            $retrievalSuccess = $true
        }
    } catch {
        Log-Warn "Git clone failed. Falling back to HTTP zip download..."
    }
}

if (-not $retrievalSuccess) {
    Log-Info "Downloading package archive zip..."
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip -UseBasicParsing
        Log-Success "Download completed successfully."
        
        Log-Info "Extracting files to installation folder..."
        if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue }
        Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force
        
        if (Test-Path $targetDir) { Remove-Item $targetDir -Recurse -Force -ErrorAction SilentlyContinue }
        $extractedFolder = Join-Path $tempExtract "AI-Runtime-Manager-main"
        Move-Item -Path $extractedFolder -Destination $targetDir -Force
        
        Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
        Log-Success "Files extracted successfully to: $targetDir"
    } catch {
        Log-Error "Failed to download code package: $_"
        Exit 1
    }
}

# 4. Invoke Bootstrapper & Installer
Log-Info "Navigating to installation folder..."
Set-Location $targetDir

# Ensure logs folder exists
New-Item -ItemType Directory -Force -Path ".\logs" | Out-Null

Log-Info "Invoking low-level bootstrapper silently (logging to .\logs\installer.log)..."
try {
    # Run bootstrap silently and redirect logs
    powershell -ExecutionPolicy Bypass -File ".\core\bootstrap.ps1" *>> ".\logs\installer.log"
} catch {
    Log-Error "Bootstrapper failed. Check .\logs\installer.log for details."
    Exit 1
}

Log-Info "Launching Web Guided Assistant..."
if (Test-Path ".\.venv\Scripts\python.exe") {
    try {
        # Launch prompt_server in the foreground as Web Control
        & ".\.venv\Scripts\python.exe" ".\core\manager.py" install
    } catch {
        Log-Error "Control assistant exited with error: $_"
        Exit 1
    }
} else {
    Log-Error "Virtual environment python was not found after bootstrap setup!"
    Exit 1
}
