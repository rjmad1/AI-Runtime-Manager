# Troubleshooting & Self-Healing Guide

AIRM is designed with built-in self-healing routines to resolve runtime failures automatically. If you encounter issues with ports, credentials, or service availability, use this guide to restore system integrity quickly.

---

## ⚡ Quick Fix: Single-Command Self-Repair

If services hang or behave unexpectedly, the fastest way to resolve configuration drift, occupied ports, or corrupted schemas is to run the self-repair batch wrapper.

**In the File Explorer:**
*   Navigate to your installation folder (e.g. `C:\Users\<username>\AI-Runtime-Manager`).
*   Double-click **`Repair.bat`**.

**From PowerShell:**
```powershell
.\Repair.bat
```

### What Self-Repair Does:
1.  Audits port bindings for `4000` (LiteLLM) and `18789` (OpenClaw) and kills any conflicting processes holding them.
2.  Inspects `settings.yaml`, `providers.yaml`, and `models.yaml` and restores defaults if file schemas are corrupted or empty.
3.  Cleans stale LiteLLM cache directories.
4.  Re-runs configuration sync pipelines to match active configurations with provider specifications.
5.  Re-installs missing library dependencies inside the local Python virtual environment.

---

## 🔍 Frequent Breakdowns & Solutions

### 1. Port Collisions (Port 4000 or 18789 Occupied)
*   **Symptom**: LiteLLM or OpenClaw fails to launch; console logs display `OSError: [Errno 98] Address already in use` or port binding failures.
*   **Cause**: A previous instance of the services did not shut down cleanly, or another application is listening on port 4000 or 18789.
*   **Solution**: Double-click **`Repair.bat`** or run **`Manage.bat stop`**. This calls AIRM's port scavenger, which runs `netstat -ano`, identifies the exact process IDs holding the ports, and kills their process trees.

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
