# install.ps1
# Single-line PowerShell bootstrapper installer for AI-Runtime-Manager (OpenClaw Workstation).
# Execution command:
# powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 | iex"

$ErrorActionPreference = "Stop"

function Write-InfoLog ($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-SuccessLog ($msg) { Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Write-WarnLog ($msg) { Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Write-ErrorLog ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Clear-Host
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-InfoLog "=========================================================="
Write-InfoLog "    OpenClaw Workstation AI Runtime Manager (AIRM)"
Write-InfoLog "=========================================================="
Write-InfoLog "Initializing zero-touch background installer..."

# 1. Resolve Installation Directory
$targetDir = Join-Path $Home "AI-Runtime-Manager"
Write-InfoLog "Target installation path resolved to: $targetDir"

if (Test-Path $targetDir) {
    Write-WarnLog "An existing installation was found at $targetDir."
    $choice = Read-Host "Would you like to overwrite it and perform a fresh install? (y/n)"
    if ($choice.ToLower().Trim() -eq 'y' -or $choice.ToLower().Trim() -eq 'yes') {
        Write-InfoLog "Cleaning up old installation..."
        try {
            $pids = @()
            Get-NetTCPConnection -LocalPort 4000, 18789 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
                $pids += $_.OwningProcess
            }
            if ($pids.Count -gt 0) {
                Write-InfoLog "Stopping active servers on ports 4000/18789..."
                Stop-Process -Id $pids -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item $targetDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-InfoLog "Installation cancelled by user."
        Exit 0
    }
}

# 2. Retrieve codebase
$repoUrl = "https://github.com/rjmad1/AI-Runtime-Manager.git"
$zipUrl = "https://github.com/rjmad1/AI-Runtime-Manager/archive/refs/heads/main.zip"
$tempZip = Join-Path $env:TEMP "AI-Runtime-Manager.zip"
$tempExtract = Join-Path $env:TEMP "AI-Runtime-Manager-extract"

Write-InfoLog "Retrieving latest release packages from GitHub..."
$retrievalSuccess = $false

$gitPath = Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if ($gitPath) {
    Write-InfoLog "Git detected. Cloning repository..."
    try {
        if (Test-Path $targetDir) { Remove-Item $targetDir -Recurse -Force -ErrorAction SilentlyContinue }
        Start-Process git -ArgumentList "clone $repoUrl `"$targetDir`"" -NoNewWindow -Wait -ErrorAction Stop
        if (Test-Path (Join-Path $targetDir "core\bootstrap.ps1")) {
            Write-SuccessLog "Repository cloned successfully via Git to: $targetDir"
            $retrievalSuccess = $true
        }
    } catch {
        Write-WarnLog "Git clone failed. Falling back to HTTP zip download..."
    }
}

if (-not $retrievalSuccess) {
    Write-InfoLog "Downloading package archive zip..."
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip -UseBasicParsing
        Write-SuccessLog "Download completed successfully."
        
        Write-InfoLog "Extracting files to installation folder..."
        if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue }
        Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force
        
        if (Test-Path $targetDir) { Remove-Item $targetDir -Recurse -Force -ErrorAction SilentlyContinue }
        $extractedFolder = Join-Path $tempExtract "AI-Runtime-Manager-main"
        Move-Item -Path $extractedFolder -Destination $targetDir -Force
        
        Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
        Write-SuccessLog "Files extracted successfully to: $targetDir"
    } catch {
        Write-ErrorLog "Failed to download code package: $_"
        Exit 1
    }
}

# 4. Invoke Bootstrapper & Installer
Write-InfoLog "Navigating to installation folder..."
Set-Location $targetDir

# Ensure logs folder exists
New-Item -ItemType Directory -Force -Path ".\logs" | Out-Null

Write-InfoLog "Invoking low-level bootstrapper silently (logging to .\logs\installer.log)..."
try {
    # Run bootstrap silently and redirect logs
    $proc = Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `".\core\bootstrap.ps1`"" -RedirectStandardOutput ".\logs\installer.log" -RedirectStandardError ".\logs\installer.log" -PassThru -Wait -NoNewWindow
    if ($proc.ExitCode -ne 0) {
        throw "Bootstrapper exited with code $($proc.ExitCode)"
    }
} catch {
    Write-ErrorLog "Bootstrapper failed. Checking logs..."
    if (Test-Path ".\logs\installer.log") {
        $logContent = Get-Content ".\logs\installer.log" -Tail 15 -ErrorAction SilentlyContinue
        Write-Host ""
        Write-Host "--- Last 15 lines of installer.log ---" -ForegroundColor Yellow
        $logContent | ForEach-Object { Write-Host $_ }
        Write-Host "--------------------------------------" -ForegroundColor Yellow
    } else {
        Write-ErrorLog "Log file .\logs\installer.log not found."
    }
    Exit 1
}

Write-InfoLog "Launching Web Guided Assistant..."
if (Test-Path ".\.venv\Scripts\python.exe") {
    try {
        # Launch prompt_server in the foreground as Web Control
        $prevErrAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & ".\.venv\Scripts\python.exe" ".\core\manager.py" install
        if ($LASTEXITCODE -ne 0) { throw "Control assistant returned non-zero exit code $LASTEXITCODE" }
        $ErrorActionPreference = $prevErrAction
    } catch {
        Write-ErrorLog "Control assistant exited with error: $_"
        Exit 1
    }
} else {
    Write-ErrorLog "Virtual environment python was not found after bootstrap setup!"
    Exit 1
}
