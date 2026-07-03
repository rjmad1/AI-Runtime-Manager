# Contributing to AI Runtime Manager (AIRM)

Welcome! We appreciate your interest in contributing to the AI Runtime Manager (AIRM). Please review this guide to understand our developer workflows, formatting standards, and coding conventions.

---

## 🛠️ Developer Environment Setup

1.  **Clone the Repository:**
    ```cmd
    git clone https://github.com/rjmad1/AI-Runtime-Manager.git
    cd AI-Runtime-Manager
    ```

2.  **Prerequisites:**
    Ensure you have Python 3.11+, Node.js LTS, and Git installed.

3.  **Bootstrap dependency environment:**
    Double-click `Install.bat` or run `install.ps1` in PowerShell. This configures the local `.venv` environment and installs pinned dependencies.

---

## 📐 Coding Standards

### Python
*   **Format:** We use **Ruff** for linting and formatting. Run `ruff check core/ tests/` to verify your changes.
*   **Type Safety:** Standard Python 3 type hints are required on all new modules and public-facing functions. Verify with `mypy core/`.
*   **No Frameworks:** The core HTTP server runs on standard library `http.server`. Avoid introducing external frameworks (such as Flask, FastAPI) to keep dependencies light and secure.

### Web Dashboard (HTML/CSS/JS)
*   **Separation of concerns:** Never embed UI styles or layout scripts directly inside Python source code. All layout must be written inside [core/templates/dashboard.html](file:///c:/Users/rajaj/Projects/OpenClaw%20InstallationEasyMethodLiteLLM/Installer%20Mode/core/templates/dashboard.html).
*   **Styling:** Use Vanilla CSS with design variables.

---

## 🧪 Testing Guidelines

We use **pytest** for unit and integration testing. Any new feature must be accompanied by corresponding tests.

### Running Tests
Inside your python environment, install dev tools and execute pytest:
```cmd
.venv\Scripts\pip.exe install ruff mypy pytest
.venv\Scripts\pytest.exe tests/ -v
```

---

## 🔒 Security Practices

1.  **Never Hardcode Secrets:** API keys and credentials must not be committed to Git or saved in YAML configurations. Utilize Windows User environment variables (`[System.Environment]`) for key persistence.
2.  **Escape Shell Outputs:** When interacting with system sub-processes or building environment variables in PowerShell, always escape values to prevent command injection.
3.  **Zip Slip Prevention:** Always apply folder target boundary verification when extracting zip archives.
4.  **XSS Prevention:** Ensure all dynamic data printed to HTML templates or logs is properly escaped using `html.escape`.
