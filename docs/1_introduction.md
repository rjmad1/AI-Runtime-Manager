# Introduction to the AIRM Ecosystem

The **AI Runtime Manager (AIRM)** is a professionally engineered, zero-touch, self-healing workstation lifecycle supervisor for Windows. It provides a unified gateway, service management console, and visual guided setup that seamlessly binds **OpenClaw**, **LiteLLM**, **Ollama**, local LLMs, and cloud API providers into a single, cohesive developer environment.

---

## 🏛️ Ecosystem Architecture

AIRM operates as a lifecycle orchestrator that decouples user configurations from runtime technical complexities. The architecture consists of four distinct operational layers:

```
                  ┌────────────────────────────────────────┐
                  │          Visual Web Browser           │
                  │   AIRM Dashboard / Control Panel UI    │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │          REST Control Service          │
                  │         (core/prompt_server.py)        │
                  └─────────┬───────────────────┬──────────┘
                            │                   │
                            ▼                   ▼
                  ┌──────────────────┐ ┌──────────────────┐
                  │  LiteLLM Proxy   │ │    OpenClaw      │
                  │   (Port 4000)    │ │  (Port 18789)    │
                  └─────────┬────────┘ └────────┬─────────┘
                            │                   │
             ┌──────────────┴──────┐            │
             ▼                     ▼            │
     ┌──────────────┐      ┌──────────────┐     │
     │  Cloud APIs  │      │  Local LLMs  │◄────┘
     │(Gemini, Groq)│      │(Ollama, GGUF)│
     └──────────────┘      └──────────────┘
```

1.  **Guided Assistant & Operations Web UI**: A stunning single-page web dashboard that handles initial setup, credential validation, operations control, benchmarks, and active process log streaming.
2.  **Daemon Lifecycle Core**: Spawns and manages LiteLLM and OpenClaw services as detached background processes, ensuring they run independently of the launching terminal.
3.  **Intelligent Discovery Engine**: Inspects Windows hardware configurations, prerequisites, and model metadata to automatically configure routing tables and hardware matches.
4.  **Gateway Routing Layer**: LiteLLM acts as a unified OpenAI-compatible routing gateway, multiplexing requests to cloud APIs and local Ollama nodes with automated fallback protection, which are then consumed by OpenClaw.

---

## 🎯 What AIRM Can Do

*   **Zero-Touch Dependency Auditing**: Automatically discovers whether Python, Git, Node, npm, uv, Ollama, and CUDA are installed, and resolves their paths on Windows.
*   **Hardware Profiling**: Collects CPU, total RAM, GPU video controller models, VRAM, and free disk space, translating raw specs into recommended model tiers.
*   **Interactive Key Validation**: Validates cloud API credentials in real-time against actual provider endpoints (Google Gemini, Groq, SambaNova, Cerebras, OpenRouter) and saves successful keys securely inside Windows User Environment Variables.
*   **Decoupled Model Cataloging**: Programmatically queries LiteLLM's local metadata database to dynamically build capabilities, context windows, and token pricing models without maintaining static hardcoded catalogs.
*   **Local Model Suitability Grading**: Calculates the parameter size of downloaded Ollama models and evaluates their compatibility with available VRAM/RAM to flag GPU acceleration capabilities or CPU fallbacks.
*   **Non-Destructive Configuration Syncing**: Merges dynamic service details (like dynamic security tokens and fallback routes) into active OpenClaw settings files (`~/.openclaw/openclaw.json`) without erasing user-customized skills, plugins, or tools.
*   **Detached Service Daemonization**: Spawns server proxies in independent process groups (`DETACHED_PROCESS`) that survive parent command-prompt shutdowns.
*   **Autonomous Self-Healing**: Scavenges occupied ports, corrects corrupted JSON/YAML configurations, cleans proxy caches, and reinstalls missing libraries.
*   **Configuration Backups**: Packages blueprints and active credentials in ZIP archives with Zip Slip security filtering, supporting instant restores.

---

## 🛑 What AIRM Cannot Do

*   **Local Model Hosting**: AIRM does not host weights or run raw inference directly. It coordinates local inference by orchestrating Ollama (or other GGUF backends) and routing them through LiteLLM.
*   **Hardware Acceleration Injection**: AIRM cannot force hardware acceleration (like CUDA) if your system lacks compatible physical hardware (NVIDIA GPU) or correct graphic drivers.
*   **Zero-Overhead Local Simulation**: It cannot run complex, large local models (e.g. Llama 70B) on low-spec workstations without extreme performance degradation. Low-spec machines are automatically advised to use remote Cloud APIs.
*   **Cross-Platform Portability (Native)**: AIRM is highly optimized for Windows workstations using PowerShell, Windows User variables, and Windows task managers. While the design is modular, it does not support native execution on macOS or Linux out of the box without script updates.
