# install.ps1
# Single-line PowerShell bootstrapper installer for AI-Runtime-Manager (OpenClaw Workstation).
# Execution command:
# powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 | iex"

$ErrorActionPreference = "Stop"

function Log-Info ($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Log-Success ($msg) { Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Log-Warn ($msg) { Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Log-Error ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Log-Info "=============================================="
Log-Info "    OpenClaw Workstation Installer (UV-Style)"
Log-Info "=============================================="

# 1. Resolve Installation Directory
$targetDir = Join-Path $Home "AI-Runtime-Manager"
Log-Info "Target installation path resolved to: $targetDir"

if (Test-Path $targetDir) {
    Log-Warn "An existing installation was found at $targetDir."
    $choice = Read-Host "Would you like to overwrite it and perform a fresh install? (y/n)"
    if ($choice.ToLower().Trim() -eq 'y' -or $choice.ToLower().Trim() -eq 'yes') {
        Log-Info "Cleaning up old installation..."
        # Stop any running processes on default ports before deleting
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

# 2. Download code base from GitHub
$zipUrl = "https://github.com/rjmad1/AI-Runtime-Manager/archive/refs/heads/main.zip"
$tempZip = Join-Path $env:TEMP "AI-Runtime-Manager.zip"
$tempExtract = Join-Path $env:TEMP "AI-Runtime-Manager-extract"

Log-Info "Downloading latest release package from GitHub..."
try {
    # Ensure TLS 1.2 is used
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip -UseBasicParsing
    Log-Success "Download completed successfully."
} catch {
    Log-Error "Failed to download code package: $_"
    Exit 1
}

# 3. Extract Archive
Log-Info "Extracting files to installation folder..."
try {
    if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue }
    Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force
    
    # Move and rename target folder
    $extractedFolder = Join-Path $tempExtract "AI-Runtime-Manager-main"
    Move-Item -Path $extractedFolder -Destination $targetDir -Force
    
    # Cleanup temp extraction
    Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
    Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
    Log-Success "Files extracted successfully to: $targetDir"
} catch {
    Log-Error "Extraction failed: $_"
    Exit 1
}

# 4. Invoke Bootstrapper & Installer
Log-Info "Navigating to installation folder..."
Set-Location $targetDir

Log-Info "Invoking dependency bootstrapper..."
try {
    powershell -ExecutionPolicy Bypass -File ".\core\bootstrap.ps1"
} catch {
    Log-Error "Bootstrapper failed: $_"
    Exit 1
}

Log-Info "Starting interactive configuration and API keys validation assistant..."
if (Test-Path ".\.venv\Scripts\python.exe") {
    try {
        & ".\.venv\Scripts\python.exe" ".\core\manager.py" install
        Log-Success "Workstation successfully configured."
    } catch {
        Log-Error "Credential configuration failed: $_"
        Exit 1
    }
} else {
    Log-Error "Virtual environment python was not found after bootstrap setup!"
    Exit 1
}

Log-Success "=============================================="
Log-Success "    OpenClaw Workstation Installed Successfully!"
Log-Success "=============================================="
Log-Info "You can now manage your system using the following commands inside $targetDir"
Log-Info "  .\Manage.bat start   - Start LiteLLM and OpenClaw"
Log-Info "  .\Manage.bat stop    - Terminate active servers"
Log-Info "  .\Diagnose.bat       - Run connection latency benchmarks"
Log-Info "=============================================="
