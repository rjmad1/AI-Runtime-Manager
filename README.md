# OpenClaw Workstation Lifecycle Manager

A self-contained, enterprise-grade, self-healing Windows installer and service manager for OpenClaw and LiteLLM. 

This manager operates on a declarative basis: the only files you edit are `settings.yaml` and `providers.yaml` inside the `OpenClawManager/` folder. All complex configurations for LiteLLM (`config.yaml`) and OpenClaw (`openclaw.json`) are compiled and maintained automatically by the lifecycle core.

---

## Quick Start (Deploy in 3 Steps)

### Step 1: Install & Set Up Credentials
Double-click **`Install.bat`** (or run it from your command prompt). 
- This automatically detects or installs Node.js, Python, Git, and `uv`.
- Creates a local isolated virtual environment (`.venv`) for python server libraries.
- Prompts you interactively for any missing API keys and saves them securely as persistent User Environment Variables.

### Step 2: Start the Servers
Run **`Manage.bat start`** (or double-click it) to spin up both LiteLLM and OpenClaw in harmony.
- LiteLLM Proxy is launched in the background on port `4000`.
- The manager polls the proxy health checker until it reports online.
- OpenClaw is then launched in the foreground on port `18789`. Press `Ctrl+C` in the console window to stop both servers cleanly.

### Step 3: Run Diagnostic Benchmarks
Open a separate terminal and double-click **`Diagnose.bat`**.
- This tests connection latency and completion integrity on all configured models.
- It will automatically launch a visual, dark-themed diagnostics dashboard (`generated/health-report.html`) in your default web browser.

---

## Entry Point Script Directory

The following command wrappers are located in the root of the directory:

*   **`Install.bat`** — Installs prerequisites, creates `.venv`, prompts for API keys, and compiles active configuration files.
*   **`Manage.bat`** — Orchestrates stack processes:
    *   `Manage.bat start` — Launches LiteLLM and OpenClaw.
    *   `Manage.bat stop` — Safely kills active servers and frees ports.
    *   `Manage.bat status` — Reports active PIDs and ports.
    *   `Manage.bat configure` — Force recompiles configuration outputs.
    *   `Manage.bat backup` — Compiles a timestamped zip of your settings.
    *   `Manage.bat restore` — Interactively prompts and restores a backup.
*   **`Diagnose.bat`** — Runs connection tests and displays the HTML benchmark dashboard.
*   **`Repair.bat`** — Scavenges processes occupying ports 4000/18789, checks configuration schemas, and clears caches.
*   **`Upgrade.bat`** — Pulls the latest LiteLLM packages via pip and updates OpenClaw globally.
*   **`Uninstall.bat`** — Shuts down servers, deletes the virtual environment, and cleans configurations.

---

## Configurations Guide

All configs reside inside the **`OpenClawManager/`** directory:

1.  **`settings.yaml`**: Customize port bindings, log levels, backup paths, and enable or disable local Ollama integration.
2.  **`providers.yaml`**: Enable/disable providers (e.g. Gemini, Groq, OpenRouter) and view console sign-up links.
3.  **`models.yaml`**: Master list of supported models, context window limits, and fallback targets (e.g. falling back to groq or gemini if SambaNova fails).
