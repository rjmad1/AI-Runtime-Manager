# AIRM Long-Term Capabilities & Development Roadmap

This document outlines the planned long-term capabilities and developmental roadmap for the AI Runtime Manager (AIRM). 

> [!IMPORTANT]
> **Status:** The capabilities described below are **not yet implemented**. They represent future enhancement opportunities planned to evolve the workspace from a local workstation installer into a production-grade, enterprise-ready multi-platform developer environment.

---

## 🗺️ Long-Term Development Roadmap

### 1. Cross-Platform Abstraction Layer (macOS & Linux Support)
*   **Goal:** Port AIRM from a Windows-only installer into a cross-platform daemon lifecycle manager.
*   **Planned Implementation:**
    *   Abstract process management out of Windows-specific toolsets (like `taskkill` and `netstat`) into native Python shell abstractions or cross-platform utilities (e.g., `psutil`).
    *   Rewrite PowerShell bootstrap routines (`bootstrap.ps1` and `install.ps1`) into bash/zsh shell scripts.
    *   Transition environment variable storage from Windows Registry (`[System.Environment]`) to platform-agnostic configurations (`~/.pam_environment`, `.bashrc`, or a local encrypted file-based secrets vault).

### 2. Plug-and-Play Provider Extensibility (Plugin Architecture)
*   **Goal:** Allow developers to register custom API providers without altering core configuration compilation logic.
*   **Planned Implementation:**
    *   Implement a base validator class (`BaseProviderValidator`) with standard interface hooks.
    *   Allow third-party plugins to be registered as standalone modules in a `core/plugins/` directory.
    *   Support dynamic loading of custom templates for endpoint URLs, authorization schemes, and latency diagnostic models.

### 3. Release Management and Semantic Versioning
*   **Goal:** Move away from mono-branch development to structured release engineering.
*   **Planned Implementation:**
    *   Adopt strict semantic versioning (`vM.N.P`) for updates.
    *   Configure GitHub Actions workflows to auto-generate draft releases and compile standard change logs.
    *   Implement an update-notifier in the Visual Control Center pointing to tag releases.

### 4. Real-Time WebSockets Push Logging
*   **Goal:** Replace REST polling log streams with low-overhead, real-time logging.
*   **Planned Implementation:**
    *   Transition dashboard backend to handle WebSocket frames.
    *   Utilize a background thread loop with a queue reader to push stdout/stderr logs from LiteLLM and OpenClaw immediately to the browser without polling requests.
