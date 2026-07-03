# AIRM REST API Reference

The AI Runtime Manager (AIRM) exposes a loopback-only control plane HTTP server on `http://127.0.0.1:8500`. This document outlines the REST API endpoints available for visual dashboards, scripting, or external workstation orchestration.

---

## 📡 GET Endpoints

### 1. Dashboard UI
*   **Path:** `GET /`
*   **Response:** `text/html`
*   **Description:** Serves the main visual workstation dashboard.

### 2. Auto-Discovery Specs
*   **Path:** `GET /api/discovery`
*   **Response:** `application/json`
*   **Description:** Returns cached system hardware profiling, installed tools audit, model tier recommendation, and local Ollama service discovery.
*   **Example Response:**
    ```json
    {
      "specs": {
        "os": "Microsoft Windows 11 Pro",
        "cpu": "Intel(R) Core(TM) i9-14900K",
        "ram_gb": 64,
        "gpus": [{"name": "NVIDIA GeForce RTX 4090", "vram_gb": 24.0}],
        "disk": {"free_gb": 420, "total_gb": 2048}
      },
      "tools": {
        "python": "C:\\Python311\\python.exe",
        "git": "C:\\Program Files\\Git\\cmd\\git.exe"
      },
      "recommendations": {
        "tier": "excellent",
        "recommendation": "System supports local model acceleration..."
      },
      "ollama": {
        "online": true,
        "api_connected": true,
        "models": [...]
      }
    }
    ```

### 3. API Key Status registry
*   **Path:** `GET /api/providers`
*   **Response:** `application/json`
*   **Description:** Returns a dictionary mapping AI providers to their status, environment variable mapping, and whether a key is configured in the Windows registry environment.
*   **Example Response:**
    ```json
    {
      "gemini": {
        "enabled": true,
        "env_var": "GEMINI_API_KEY",
        "info": "Free tier available at Google AI Studio...",
        "has_key": true
      }
    }
    ```

### 4. Daemon Services Status
*   **Path:** `GET /api/status`
*   **Response:** `application/json`
*   **Description:** Inspects process and port bindings, returning daemon lifecycle state and the last 50 lines of system logs.

### 5. Setup Progress Status
*   **Path:** `GET /api/install/status`
*   **Response:** `application/json`
*   **Description:** Returns the thread-safe guided installation status, current step, remaining duration, and installation console logs.

### 6. Available Backups
*   **Path:** `GET /api/backups`
*   **Response:** `application/json`
*   **Description:** Returns a list of ZIP files found in the configured backups directory.

---

## 📥 POST Endpoints

### 7. Save & Validate API Key
*   **Path:** `POST /api/providers/validate`
*   **Request Body:**
    ```json
    {
      "provider": "gemini",
      "api_key": "YOUR_API_KEY_HERE"
    }
    ```
*   **Description:** Verifies key correctness by sending a minimal test payload to the provider endpoint (using headers, not URLs). Saves valid keys in Windows User registry variables.

### 8. Toggle Provider State
*   **Path:** `POST /api/providers/toggle`
*   **Request Body:**
    ```json
    {
      "provider": "gemini",
      "enabled": true
    }
    ```
*   **Description:** Enables or disables an AI provider in `providers.yaml`.

### 9. Launch Auto-Installation
*   **Path:** `POST /api/install`
*   **Description:** Spawns a background thread worker to build configuration files, generate secure dynamic tokens, and deploy background daemons.

### 10. Service Lifecycle Control
*   **Path:** `POST /api/control`
*   **Request Body:**
    ```json
    {
      "action": "start" // "start", "stop", or "restart"
    }
    ```
*   **Description:** Triggers start/stop/restart sequences for the service stack.

### 11. Run Self-Healing Repair
*   **Path:** `POST /api/repair`
*   **Description:** Triggers port scavenging, YAML schema verification, LiteLLM cache cleaning, and dependency verification.

### 12. Create Backup Zip
*   **Path:** `POST /api/backup`
*   **Description:** Bundles active blueprints and configurations into a timestamped zip archive.

### 13. Restore Backup Zip
*   **Path:** `POST /api/restore`
*   **Request Body:**
    ```json
    {
      "index": 0
    }
    ```
*   **Description:** Extracts configuration files from the selected backup zip with traversal protection.

### 14. Execute Latency Benchmarks
*   **Path:** `POST /api/diagnose`
*   **Description:** Benchmarks configured endpoints and updates HTML/Markdown latency health reports.
