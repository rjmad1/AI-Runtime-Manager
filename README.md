# OpenClaw Workstation AI Runtime Manager (AIRM)

[![CI](https://github.com/rjmad1/AI-Runtime-Manager/actions/workflows/ci.yml/badge.svg)](https://github.com/rjmad1/AI-Runtime-Manager/actions/workflows/ci.yml)
An enterprise-grade, zero-touch, self-healing Windows installer and daemon management center for OpenClaw, LiteLLM, and Ollama.

AIRM automatically discovers operating system, CPU, GPU, VRAM, and RAM specs; validates cloud credentials in real-time; routes queries across providers with fallback safety; monitors daemon health; and auto-recovers from port locks and configuration drift.

---

## 📖 System Documentation

We have compiled comprehensive guides inside the **[`docs/`](docs/)** directory to help you deploy, configure, and maintain the ecosystem:

1.  **[Ecosystem Introduction](docs/1_introduction.md)**: Explore the architectural layers of AIRM and audit what the platform can and cannot do.
2.  **[Installation Instructions](docs/2_installation.md)**: Simple copy-paste commands to deploy system prerequisites and launch the browser control assistant.
3.  **[Troubleshooting & Self-Healing](docs/3_troubleshooting.md)**: Diagnose port collisions, registry environment variable lag, and run automated self-repair.
4.  **[Enterprise Use Cases](docs/4_use_cases.md)**: Real-world scenarios where AIRM's fallback routing and visual deployment shine.
5.  **[Maximizing Value](docs/5_maximizing_value.md)**: Advanced tuning for LiteLLM routing, local model quantization checks, and backup scheduling.

---

## ⚡ Quick-Start

### Recommended: Verified Install

Clone the repository (or download the installer) so you can inspect exactly what will run on your machine, then launch the installer:

```powershell
git clone https://github.com/rjmad1/AI-Runtime-Manager.git
cd AI-Runtime-Manager
# Review install.ps1 / Install.bat before executing, then:
.\Install.bat
```

Alternatively, download just the bootstrap script and review it before running:

```powershell
iwr https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 -OutFile install.ps1
# Inspect the script (e.g. notepad install.ps1), then:
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### Convenience: Single-Command Install

If you accept running a remote script without prior inspection, the one-liner below performs the same bootstrap:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/rjmad1/AI-Runtime-Manager/main/install.ps1 | iex"
```

Once prerequisites are configured silently, the installer launches the **Visual Setup Assistant** in your browser (`http://127.0.0.1:8500`) to validate credentials, map local models, and start the background services.

---

## ⚙️ Service Command Wrappers

AIRM runs services in independent process groups. Once installed, use the following batch scripts inside the workspace directory:

*   **`Manage.bat start`** — Launches the LiteLLM Proxy and OpenClaw Gateway as background daemons and polls readiness.
*   **`Manage.bat stop`** — Terminates active background processes and releases port bindings.
*   **`Manage.bat status`** — Reports active daemon process IDs and TCP listener ports.
*   **`Manage.bat configure`** — Manually compiles LiteLLM configurations and active settings maps.
*   **`Manage.bat backup`** — Generates a timestamped zip backup of active blueprints.
*   **`Manage.bat restore`** — Interactively lists backups and performs a secure restore.
*   **`Manage.bat watch`** — Runs the self-healing watchdog: monitors both daemons and auto-restarts them (with backoff) if they crash.
*   **`Manage.bat diagnose`** — Runs connection latency benchmarks against active model endpoints.
*   **`Manage.bat repair`** — Executes automated repair (frees port conflicts, checks YAML schemas, resets caches).
*   **`Manage.bat upgrade`** — Pulls package upgrades inside the virtual environment.
*   **`Manage.bat uninstall`** — Shuts down stack daemons, cleans environment variables, and removes files.
