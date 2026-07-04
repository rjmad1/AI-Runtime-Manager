# Troubleshooting & Self-Healing Guide

AIRM is designed with built-in self-healing routines to resolve runtime failures automatically. If you encounter issues with ports, credentials, or service availability, use this guide to restore system integrity quickly.

---

## ⚡ Quick Fix: Single-Command Self-Repair

If services hang or behave unexpectedly, the fastest way to resolve configuration drift, occupied ports, or corrupted schemas is to run the self-repair batch wrapper.

**In the File Explorer:**
*   Navigate to your installation folder (e.g. `C:\Users\<username>\AI-Runtime-Manager`).
*   Run **`Manage.bat repair`**.

**From PowerShell:**
```powershell
.\Manage.bat repair
```

### What Self-Repair Does:
1.  Audits port bindings for `4000` (LiteLLM) and `18789` (OpenClaw) and kills any conflicting processes holding them.
2.  Inspects `settings.yaml`, `providers.yaml`, and `models.yaml` and restores defaults if file schemas are corrupted or empty.
3.  Cleans stale LiteLLM cache directories.
4.  Re-runs configuration sync pipelines to match active configurations with provider specifications.
5.  Re-installs missing library dependencies inside the local Python virtual environment.
6.  Audits the enterprise dependency inventory (git, python, node, uv, ollama, GPU stacks, WSL, virtualization) and offers to install missing auto-installable dependencies via the platform package manager (winget on Windows, Homebrew on macOS) — each install requires your explicit `yes`. Heavy or privileged dependencies (Docker, CUDA, ROCm, drivers) get guided instructions instead. Every run writes an audit trail to `generated/repair-report.json`.

---

## 🧬 Version Migrations (Upgrades & Downgrades)

Configuration and artifact schema changes between AIRM versions are handled by the migration framework. Migrations run **automatically** at every CLI/dashboard startup; a pre-migration backup ZIP is always taken first and restored automatically if a migration fails. Inspect and control migrations manually:

```powershell
.\Manage.bat migrate status                # current/latest schema version, pending steps, history
.\Manage.bat migrate                       # apply pending migrations now
.\Manage.bat migrate rollback <version>    # walk reversible downgrades back to <version>
```

If the schema on disk is **newer** than the installed AIRM build (i.e. you downgraded the app), AIRM refuses to start and tells you to upgrade or restore a backup — old code never touches state it does not understand. Irreversible migrations are marked in `migrate status`; rolling across them requires restoring a pre-migration backup (`Manage.bat restore`).

---

## 🗂 Configuration Versioning

Every change AIRM makes to `settings.yaml`, `providers.yaml`, or `models.yaml` snapshots the previous version first (kept under `OpenClawManager/history/`, last 100 per file). Hand-edits made outside AIRM are detected as conflicts, flagged in the history, and preserved before being overwritten. All events land in the `logs/audit.log` trail.

```powershell
.\Manage.bat history list                 # numbered history (tags and external-edit flags shown)
.\Manage.bat history diff <id>            # unified diff: snapshot → current file
.\Manage.bat history rollback <id>        # restore a snapshot (reversible — current state is snapshotted first)
.\Manage.bat history tag <id>             # label a known-good version
```

`history rollback` automatically recompiles the LiteLLM/OpenClaw blueprints from the restored configuration.

---

## 🐕 Continuous Self-Healing: The Watchdog

For unattended operation, run the watchdog instead of waiting for something to break:

```powershell
.\Manage.bat watch
```

The watchdog polls both daemons every 15 seconds. If either the LiteLLM Proxy or the OpenClaw Gateway dies, it restarts the full stack automatically (stop → port scavenge → reconfigure → start). Repeated restart failures back off exponentially (capped at 5 minutes) so a hard-broken installation is never restart-hammered. Press `Ctrl+C` to stop supervision; on Linux/macOS use `./manage.sh watch`.

To keep the watchdog itself alive across reboots, register it with your platform's scheduler (a Windows Task Scheduler "At log on" task, or a systemd/launchd user service running `manage.sh watch`).

---

## 🔍 Frequent Breakdowns & Solutions

### 1. Port Collisions (Port 4000 or 18789 Occupied)
*   **Symptom**: LiteLLM or OpenClaw fails to launch; console logs display `OSError: [Errno 98] Address already in use` or port binding failures.
*   **Cause**: A previous instance of the services did not shut down cleanly, or another application is listening on port 4000 or 18789.
*   **Solution**: Run **`Manage.bat repair`** or **`Manage.bat stop`**. This calls AIRM's port scavenger, which runs `netstat -ano`, identifies the exact process IDs holding the ports, and kills their process trees.

### 2. "LiteLLM Proxy is Offline" / "Cannot Execute Diagnostics"
*   **Symptom**: Starting the gateway fails, or running diagnostics logs `[ERROR] LiteLLM Proxy is OFFLINE`.
*   **Cause**: LiteLLM failed to initialize. Common causes include missing API keys for enabled providers, firewall blocks on localhost, or syntax errors in custom configs.
*   **Solution**:
    1.  Inspect **`logs/litellm.log`** to read the exact error output from the LiteLLM uvicorn server.
    2.  Open **`OpenClawManager/providers.yaml`** and ensure that any provider toggled to `enabled: true` has its corresponding API key set in your Windows system environment. If not, toggle it to `false` or set the API key.
    3.  Run **`Manage.bat configure`** to rebuild configuration files, then restart the stack.

### 3. Registry Lag (API Keys Saved but Services Fail to Detect)
*   **Symptom**: You saved and validated an API key in the browser setup wizard, but the console logs still report `API Key not configured` when starting services.
*   **Cause**: Windows User Environment Variables are saved persistently in the registry, but the currently active command-prompt session was launched before the environment refresh and is reading stale cached variables.
*   **Solution**:
    *   Close your active terminal window and open a **new** Command Prompt or PowerShell session. This forces Windows to reload the registry environment variables.
    *   Alternatively, run **`Manage.bat start`** which programmatically queries the latest registry values using PowerShell and loads them directly into the startup process environment.

### 4. Ollama Service Unreachable
*   **Symptom**: AIRM fails to auto-discover local GGUF models or reports `Ollama is offline`.
*   **Cause**: Ollama is not installed, or the Ollama background daemon is stopped, or the API host path binds to a custom port.
*   **Solution**:
    1.  Verify if Ollama is installed on your system.
    2.  In **`OpenClawManager/settings.yaml`**, verify that `ollama.enabled` is `true` and the `api_base` matches your Ollama port (default is `http://127.0.0.1:11434`).
    3.  If `ollama.autostart` is `true`, AIRM will attempt to spawn Ollama in the background on startup. You can manually launch it by double-clicking the Ollama tray icon.
