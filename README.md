# OpenClaw Workstation Lifecycle Manager

A self-contained, enterprise-grade, self-healing Windows installer and service manager for OpenClaw and LiteLLM. 

This manager operates on a declarative basis: the only files you edit are `settings.yaml` and `providers.yaml` inside the `OpenClawManager/` folder. All complex configurations for LiteLLM (`config.yaml`) and OpenClaw (`openclaw.json`) are compiled and maintained automatically by the lifecycle core.

---

## 🚀 Quick Start (Single-Command Install)

To deploy the entire workstation, dependencies, virtual environment, and configurations automatically on any clean Windows machine, open a PowerShell terminal and run:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 | iex"
```

### What this does:
1. Resolves the installation folder at `~/AI-Runtime-Manager` and retrieves the code from GitHub.
2. Checks for and installs system prerequisites (Git, Python 3.11+, Node.js LTS, and `uv`) automatically.
3. Spawns a **Visual Browser Assistant** to configure API keys for your enabled AI providers securely on your local machine.
4. Compiles LiteLLM routing configurations (`config.yaml`) and maps fallbacks dynamically.
5. Automatically merges configurations with your active OpenClaw settings.

---

## Service Management Commands

Once installed, navigate to `~/AI-Runtime-Manager` and run the following batch command wrappers:

*   **`Manage.bat start`** — Launches the LiteLLM Proxy in the background, polls for health, and boots the OpenClaw Gateway in the foreground.
*   **`Manage.bat stop`** — Gracefully stops all active server processes and scavenges ports 4000/18789.
*   **`Manage.bat status`** — Reports active process IDs and port bindings.
*   **`Manage.bat configure`** — Compiles configuration outputs manually.
*   **`Manage.bat backup`** — Creates a timestamped zip backup of your keys and YAML settings.
*   **`Manage.bat restore`** — Interactively lists backups and performs a secure, Zip Slip protected restore.
*   **`Diagnose.bat`** — Runs connection latency benchmarks against configured models and launches the HTML dashboard.
*   **`Repair.bat`** — Automatically clears dangling processes, frees ports, audits config schemas, and clears caches.
*   **`Upgrade.bat`** — Pulls the latest LiteLLM packages and updates the OpenClaw package version.
*   **`Uninstall.bat`** — Shuts down servers, cleans environment configurations, and removes the workspace.

---

## Configuration Files

All editable settings reside in the **`OpenClawManager/`** directory:

1.  **`settings.yaml`**: Customize port configurations, log levels, backup destinations, and Ollama integration settings.
2.  **`providers.yaml`**: Toggle API provider integrations (Gemini, Groq, SambaNova, Cerebras, OpenRouter).
3.  **`models.yaml`**: Configure models routing, context limits, and active fallback models (e.g. falling back from Gemini to Groq).
