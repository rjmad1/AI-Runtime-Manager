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
    *   AIRM saves valid keys directly to your secure Windows environment registry.
3.  **Enable Local Models**: If Ollama is running, select any local models you wish to use. The UI will indicate whether your VRAM supports them.
4.  **Click 'Launch Auto Installation'**: AIRM will compile LiteLLM configs, sync OpenClaw gateways, and boot up both background service daemons. You can close the browser setup page once finalized.
