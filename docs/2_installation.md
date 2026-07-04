# Simple Installation Guide

Deploy the entire AI Runtime Manager (AIRM) workstation, system prerequisites, and visual dashboards automatically using these clean instructions.

---

## ✅ Recommended: Verified Installation

Download the bootstrap script first so you can review what will run on your machine, then execute it:

```powershell
iwr https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 -OutFile install.ps1
# Inspect the script (e.g. notepad install.ps1), then:
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

You can also clone the repository with `git clone https://github.com/rjmad1/AI-Runtime-Manager.git` and run `Install.bat` from the checkout — every script is inspectable before execution.

---

## ⚡ Quick-Start: Single-Command Installation

If you accept running a remote script without prior inspection, deploy the entire stack automatically by pasting the following into a standard PowerShell terminal:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 | iex"
```

### What This Command Does:
1.  Resolves your target installation path to `C:\Users\<username>\AI-Runtime-Manager`.
2.  Retrieves the latest production-ready packages from GitHub.
3.  Performs a silent system prerequisite check (installing Git, Python 3.11+, Node.js LTS, and `uv` via winget if missing).
4.  Sets up a Python virtual environment and installs LiteLLM, PyYAML, and requests dependencies.
5.  Launches the **Visual Web Assistant** dashboard in your default web browser to configure API credentials and start services.

---

## 📂 Manual Installation (Local Extraction)

If you have downloaded the repository as a ZIP archive:

1.  **Extract the archive** to your desired folder (e.g. `C:\AI-Runtime-Manager`).
2.  **Open the folder** in File Explorer.
3.  **Double-click `Install.bat`** to run the bootstrapping process.
4.  Once the terminal completes the silent prerequisite check, it will automatically open the **Web Guided Setup** in your default web browser (`http://127.0.0.1:8500`).

---

## 🧭 Visual Guided Setup Steps

Once the browser assistant dashboard opens:

1.  **System Specs Review**: Verify your automatically discovered hardware tier, GPU, and system resources.
2.  **Enter Provider API Keys**: Select the tabs for your enabled providers (e.g., Gemini, Groq) and input your credentials.
    *   Click **Save & Validate** to test key connectivity in real-time.
    *   AIRM saves valid keys into the native OS credential store (Windows Credential Manager with DPAPI encryption at rest, macOS Keychain, or Linux Secret Service). Keys found in legacy plaintext locations (registry environment variables, `~/.airm_env`) are automatically promoted into the store on first read; every write, rotation, and deletion is audit-logged to `logs/audit.log` (names only — never values). Manage keys from the CLI with `Manage.bat secret list|set|rotate|delete <ENV_VAR>`. Enterprise vault read-through (HashiCorp Vault, Azure Key Vault, AWS Secrets Manager) can be enabled via the `secrets:` section in `settings.yaml` using each vault's official CLI.
3.  **Enable Local Models**: If Ollama is running, select any local models you wish to use. The UI will indicate whether your VRAM supports them.
4.  **Click 'Launch Auto Installation'**: AIRM will compile LiteLLM configs, sync OpenClaw gateways, and boot up both background service daemons. You can close the browser setup page once finalized.

---

## 🔁 Run AIRM as an OS Service (Boot Persistence)

Register the self-healing watchdog as a native OS service so the stack auto-starts at boot and is restarted by the OS if the watchdog itself ever dies (two-tier supervision: the OS supervises the watchdog, the watchdog supervises the daemons).

**Windows (elevated PowerShell):**
```powershell
.\Manage.bat service install    # Windows Service: delayed auto-start, restart-on-failure (5s/10s/30s), Event Log integration
.\Manage.bat service status     # RUNNING / STOPPED / not installed
.\Manage.bat service uninstall
```
> The service runs as `LocalSystem`. Provider API keys stored as **user** environment variables are not visible to it — either set the keys at **Machine** scope, or switch the service to run as your account in `services.msc` → Log On tab. Service start/stop/crash events are written to the Windows **Application Event Log** (source: AIRM).

**Linux (no root required — systemd user unit):**
```bash
./manage.sh service install     # writes ~/.config/systemd/user/airm.service, enables at boot, Restart=on-failure
./manage.sh service status
./manage.sh service uninstall
```
> `loginctl enable-linger` is applied best-effort so the unit starts at boot without an active login session. For a system-wide deployment, copy the generated unit to `/etc/systemd/system/` and adjust `User=`.

Stopping the service stops **supervision only** — running daemons keep serving. Use `Manage.bat stop` to stop the daemons themselves.
