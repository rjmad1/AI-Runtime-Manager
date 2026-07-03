# OpenClaw Workstation AI Runtime Manager (AIRM)

An enterprise-grade, zero-touch, self-healing Windows installer and daemon management center for OpenClaw, LiteLLM, and Ollama.

AIRM automatically discovers operating system, CPU, GPU, VRAM, and RAM specs; validates cloud credentials in real-time; routes queries across providers with fallback safety; monitors daemon health; and auto-recovers from port locks and configuration drift.

---

## 📖 System Documentation

We have compiled comprehensive guides inside the **[`docs/`](file:///c:/Users/rajaj/Projects/OpenClaw%20InstallationEasyMethodLiteLLM/Installer%20Mode/docs/)** directory to help you deploy, configure, and maintain the ecosystem:

1.  **[Ecosystem Introduction](file:///c:/Users/rajaj/Projects/OpenClaw%20InstallationEasyMethodLiteLLM/Installer%20Mode/docs/1_introduction.md)**: Explore the architectural layers of AIRM and audit what the platform can and cannot do.
2.  **[Installation Instructions](file:///c:/Users/rajaj/Projects/OpenClaw%20InstallationEasyMethodLiteLLM/Installer%20Mode/docs/2_installation.md)**: Simple copy-paste commands to deploy system prerequisites and launch the browser control assistant.
3.  **[Troubleshooting & Self-Healing](file:///c:/Users/rajaj/Projects/OpenClaw%20InstallationEasyMethodLiteLLM/Installer%20Mode/docs/3_troubleshooting.md)**: Diagnose port collisions, registry environment variable lag, and run automated self-repair.
4.  **[Enterprise Use Cases](file:///c:/Users/rajaj/Projects/OpenClaw%20InstallationEasyMethodLiteLLM/Installer%20Mode/docs/4_use_cases.md)**: Real-world scenarios where AIRM's fallback routing and visual deployment shine.
5.  **[Maximizing Value](file:///c:/Users/rajaj/Projects/OpenClaw%20InstallationEasyMethodLiteLLM/Installer%20Mode/docs/5_maximizing_value.md)**: Advanced tuning for LiteLLM routing, local model quantization checks, and backup scheduling.

---

## ⚡ Quick-Start (Single-Command Install)

To deploy the entire workstation, virtual environment, and background daemons automatically, open a standard PowerShell terminal and run:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 | iex"
```

Once prerequisites are configured silently, this command launches the **Visual Setup Assistant** in your browser (`http://127.0.0.1:8500`) to validate credentials, map local models, and start the background services.

---

## ⚙️ Service Command Wrappers

AIRM runs services in independent process groups. Once installed, use the following batch scripts inside the workspace directory:

*   **`Manage.bat start`** — Launches the LiteLLM Proxy and OpenClaw Gateway as background daemons and polls readiness.
*   **`Manage.bat stop`** — Terminates active background processes and releases port bindings.
*   **`Manage.bat status`** — Reports active daemon process IDs and TCP listener ports.
*   **`Manage.bat configure`** — Manually compiles LiteLLM configurations and active settings maps.
*   **`Manage.bat backup`** — Generates a timestamped zip backup of active blueprints.
*   **`Manage.bat restore`** — Interactively lists backups and performs a secure restore.
*   **`Diagnose.bat`** — Runs connection latency benchmarks against active model endpoints.
*   **`Repair.bat`** — Executes automated self-healing (frees port conflicts, checks YAML schemas, resets caches).
*   **`Upgrade.bat`** — Pulls package upgrades inside the virtual environment.
*   **`Uninstall.bat`** — Shuts down stack daemons, cleans environment variables, and removes files.
