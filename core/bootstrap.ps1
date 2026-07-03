# core/bootstrap.ps1
# Low-level bootstrap to verify and install system dependencies, then set up Python virtual environment.

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Helper to run native commands without stderr causing terminating exceptions
function Invoke-NativeCommand {
    param ([scriptblock]$Command)
    $prevErrAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) { throw "Command exited with code $LASTEXITCODE" }
    } finally {
        $ErrorActionPreference = $prevErrAction
    }
}

# Helper for colorful logging
function Log-Info ($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Log-Success ($msg) { Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Log-Warn ($msg) { Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Log-Error ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Log-Info "=============================================="
Log-Info "      OpenClaw Workstation Bootstrapper"
Log-Info "=============================================="

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Log-Success "Running in an elevated Administrator session."
} else {
    Log-Warn "Running in a standard user session (non-elevated). Some automated software installations may require elevation or UAC prompts."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$installModeDir = Split-Path -Parent $scriptDir
$venvDir = Join-Path $installModeDir ".venv"

# --- Pre-flight Check: Write Permissions ---
try {
    $testFile = Join-Path $installModeDir ".write_test"
    [IO.File]::WriteAllText($testFile, "test")
    Remove-Item $testFile -Force -ErrorAction SilentlyContinue
} catch {
    Log-Error "Cannot write to installation directory ($installModeDir). Please check folder permissions or run as Administrator."
    Exit 1
}

# --- 1. Detect & Install Git ---
$gitPath = Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if (-not $gitPath -and (Test-Path "C:\Program Files\Git\cmd\git.exe")) {
    $gitPath = "C:\Program Files\Git\cmd\git.exe"
}
if ($gitPath) {
    Log-Success "Git detected: $gitPath"
} else {
    Log-Warn "Git not detected. Attempting to install via winget..."
    try {
        Start-Process winget -ArgumentList "install --silent --accept-source-agreements --accept-package-agreements Git.Git" -NoNewWindow -Wait
        $gitPath = Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
        if ($gitPath) {
            Log-Success "Git installed successfully."
        } else {
            throw "Git install succeeded but 'git' command is still not in PATH."
        }
    } catch {
        Log-Error "Failed to install Git. Please install Git manually from https://git-scm.com/"
        Exit 1
    }
}

# --- 2. Detect & Install Python ---
$pythonPath = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if (-not $pythonPath -and (Test-Path "C:\Python314\python.exe")) {
    $pythonPath = "C:\Python314\python.exe"
} elseif (-not $pythonPath -and (Test-Path "$env:LocalAppData\Programs\Python\Python311\python.exe")) {
    $pythonPath = "$env:LocalAppData\Programs\Python\Python311\python.exe"
}

if ($pythonPath) {
    Log-Success "Python detected: $pythonPath"
} else {
    Log-Warn "Python not detected. Attempting to install Python 3.11 via winget..."
    try {
        Start-Process winget -ArgumentList "install --silent --accept-source-agreements --accept-package-agreements Python.Python.3.11" -NoNewWindow -Wait
        # Refresh env path
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $pythonPath = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
        if ($pythonPath) {
            Log-Success "Python installed successfully."
        } else {
            throw "Python install succeeded but 'python' command is still not in PATH."
        }
    } catch {
        Log-Error "Failed to install Python. Please install Python 3.10+ manually."
        Exit 1
    }
}

# --- 3. Detect & Install Node.js & npm ---
$nodePath = Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if (-not $nodePath -and (Test-Path "C:\Program Files\nodejs\node.exe")) {
    $nodePath = "C:\Program Files\nodejs\node.exe"
}

if ($nodePath) {
    Log-Success "Node.js detected: $nodePath"
} else {
    Log-Warn "Node.js not detected. Attempting to install Node.js LTS via winget..."
    try {
        Start-Process winget -ArgumentList "install --silent --accept-source-agreements --accept-package-agreements OpenJS.NodeJS.LTS" -NoNewWindow -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $nodePath = Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
        if ($nodePath) {
            Log-Success "Node.js installed successfully."
        } else {
            throw "Node.js install succeeded but 'node' command is still not in PATH."
        }
    } catch {
        Log-Error "Failed to install Node.js. Please install Node.js LTS manually."
        Exit 1
    }
}

# --- 4. Detect & Install uv ---
$uvPath = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if (-not $uvPath -and (Test-Path "C:\Python314\Scripts\uv.exe")) {
    $uvPath = "C:\Python314\Scripts\uv.exe"
} elseif (-not $uvPath -and (Test-Path "$env:UserProfile\.local\bin\uv.exe")) {
    $uvPath = "$env:UserProfile\.local\bin\uv.exe"
}

if ($uvPath) {
    Log-Success "uv detected: $uvPath"
} else {
    Log-Warn "uv not detected. Attempting to install uv using pip..."
    try {
        Invoke-NativeCommand { & $pythonPath -m pip install uv --user }
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $uvPath = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
        if (-not $uvPath) {
            $uvPath = "$env:UserProfile\.local\bin\uv.exe"
        }
        if (Test-Path $uvPath) {
            Log-Success "uv installed successfully at $uvPath."
        } else {
            throw "uv install via pip succeeded but executable was not found."
        }
    } catch {
        Log-Warn "Failed to install uv via pip. Attempting official installation script..."
        try {
            Invoke-Expression (Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1")
            $uvPath = "$env:UserProfile\.local\bin\uv.exe"
            if (Test-Path $uvPath) {
                Log-Success "uv installed successfully via official script."
            } else {
                throw "uv install script completed but uv.exe not found at $uvPath."
            }
        } catch {
            Log-Error "Failed to install uv. Please install uv manually: pip install uv"
            Exit 1
        }
    }
}

# --- 5. Create Python Virtual Environment (.venv) ---
if (Test-Path $venvDir) {
    Log-Info "Local virtual environment already exists at $venvDir."
} else {
    Log-Info "Creating local virtual environment in $venvDir using uv..."
    try {
        Set-Location $installModeDir
        Invoke-NativeCommand { & $uvPath venv .venv }
        Log-Success "Virtual environment created."
    } catch {
        Log-Error "Failed to create virtual environment."
        Exit 1
    }
}

# --- 6. Install Python Dependencies in .venv ---
Log-Info "Installing python dependencies (litellm, pyyaml, requests) inside .venv..."
$venvPip = Join-Path $venvDir "Scripts\uv.exe"
if (-not (Test-Path $venvPip)) {
    $venvPip = $uvPath
}
try {
    # Run uv pip install with pinned versions
    if ($venvPip -eq $uvPath) {
        Invoke-NativeCommand { & $uvPath pip install --python "$venvDir\Scripts\python.exe" pyyaml==6.0.3 "litellm[proxy]==1.90.2" requests==2.34.2 }
    } else {
        # If uv is copied in venv, use it
        Invoke-NativeCommand { & $venvDir\Scripts\uv.exe pip install pyyaml==6.0.3 "litellm[proxy]==1.90.2" requests==2.34.2 }
    }
    Log-Success "Python dependencies installed in .venv."
} catch {
    Log-Error "Failed to install Python dependencies inside .venv."
    Exit 1
}

# --- 7. Detect & Install OpenClaw (Global/Local) ---
$localClawPath = Join-Path $installModeDir "node_modules\openclaw\dist\index.js"
$globalClawPath = Get-Command openclaw -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
if (-not $globalClawPath -and (Test-Path "$env:AppData\npm\openclaw.ps1")) {
    $globalClawPath = "$env:AppData\npm\openclaw.ps1"
}

if (Test-Path $localClawPath) {
    Log-Success "Local OpenClaw installation detected at $localClawPath"
} elseif ($globalClawPath) {
    Log-Success "Global OpenClaw installation detected at $globalClawPath"
} else {
    Log-Warn "OpenClaw not detected. Attempting to install openclaw globally..."
    $globalInstallSuccess = $false
    try {
        # Try global install first
        Start-Process cmd.exe -ArgumentList "/c npm install -g openclaw" -NoNewWindow -Wait -ErrorAction Stop
        # Check global path
        $globalClawPath = Get-Command openclaw -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition
        if (-not $globalClawPath -and (Test-Path "$env:AppData\npm\openclaw.ps1")) {
            $globalClawPath = "$env:AppData\npm\openclaw.ps1"
        }
        if ($globalClawPath) {
            Log-Success "OpenClaw installed globally successfully."
            $globalInstallSuccess = $true
        }
    } catch {
        Log-Warn "Global OpenClaw installation failed (possibly due to permissions)."
    }

    if (-not $globalInstallSuccess) {
        Log-Warn "Attempting local installation inside project folder to bypass permissions..."
        try {
            Set-Location $installModeDir
            Start-Process cmd.exe -ArgumentList "/c npm install openclaw" -NoNewWindow -Wait -ErrorAction Stop
            if (Test-Path $localClawPath) {
                Log-Success "OpenClaw installed locally successfully."
            } else {
                throw "Local index.js not found after installation."
            }
        } catch {
            Log-Error "Failed to install OpenClaw globally or locally. Please install Node/npm and run 'npm install openclaw' manually in the project folder."
            Exit 1
        }
    }
}

Log-Success "Bootstrap phase completed successfully."
