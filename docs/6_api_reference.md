# AIRM REST API Reference

The AI Runtime Manager (AIRM) exposes a loopback-only control plane HTTP server on `http://127.0.0.1:8500`. This document outlines the REST API endpoints available for visual dashboards, scripting, or external workstation orchestration.

## 🔐 Authentication & Authorization

All state-changing `POST` endpoints require a Bearer credential. Three credential types are accepted:

1. **Session token** — generated fresh on every server start and printed to the terminal (the dashboard receives it automatically via the launch URL). Grants full `admin`.
2. **JWT** — obtained from `POST /api/auth/login` with a local user's credentials (create users with `Manage.bat user add <name>`). Carries the user's role; expires after 12 hours.
3. **API key** — issued with `Manage.bat apikey create <name>` (prefix `airm_`, stored as a SHA-256 digest, shown once). Can be scoped to a subset of its role's permissions and marked as a **service identity** for machine-to-machine callers.

**RBAC roles:** `admin` (everything) · `operator` (`read`, `control`) · `viewer` (`read`). Endpoint permission requirements: provider validate/toggle and install need `configure`; control/repair/backup/restore/diagnose need `control`. Missing credential → `401`; valid credential without the permission → `403`. Auth events (logins, failures, key issuance/revocation) are audit-logged to `logs/audit.log`.

> External IdP federation (OAuth2 / OIDC / SAML / LDAP) is intentionally not implemented at this layer — it arrives with the Enterprise Security Integration capability, which plugs into the same identity model.

Pass the token as a Bearer header when scripting:

```bash
# Without a token → 401
curl -i -X POST http://127.0.0.1:8500/api/control \
  -H 'Content-Type: application/json' -d '{"action":"stop"}'

# With the token printed at server start → 200
curl -i -X POST http://127.0.0.1:8500/api/control \
  -H "Authorization: Bearer <token>" \
  -H 'Content-Type: application/json' -d '{"action":"stop"}'
```

`GET` endpoints are read-only and unauthenticated.

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

### 2b. Enterprise Dependency Inventory
*   **Path:** `GET /api/inventory`
*   **Response:** `application/json`
*   **Description:** Returns the enterprise dependency inventory: command-line runtimes and tools (git, python, node, npm, uv, java, docker, ollama), GPU driver and SDK stacks (NVIDIA driver, CUDA, ROCm), platform features (WSL, hardware virtualization), hardware specs, and detected GPU vendors. Each item reports `status` (`present`/`missing`/`unknown`), `version`, and `path`. Results are cached for 5 minutes. The same report is available from the CLI via `Manage.bat inventory` (written to `generated/dependency-inventory.json`).
*   **Example Response:**
    ```json
    {
      "schema_version": 1,
      "generated_at": "2026-07-04T10:00:00+00:00",
      "platform": {"os": "Windows 11", "machine": "AMD64"},
      "gpu_vendors": ["nvidia"],
      "items": [
        {"name": "python", "category": "runtime", "status": "present", "version": "3.14.0", "path": "C:\\Python314\\python.exe", "details": ""},
        {"name": "cuda", "category": "gpu_sdk", "status": "present", "version": "12.4", "path": "C:\\...\\CUDA\\v12.4", "details": "CUDA v12.4 (nvcc)"},
        {"name": "rocm", "category": "gpu_sdk", "status": "missing", "version": "", "path": "", "details": ""}
      ],
      "summary": {"present": 10, "missing": 3}
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

### 6b. Login (JWT Issuance)
*   **Path:** `POST /api/auth/login`
*   **Request Body:** `{"username": "alice", "password": "..."}`
*   **Response:** `{"success": true, "token": "<jwt>", "role": "operator", "expires_in": 43200}`
*   **Description:** Exchanges local user credentials for an HS256 JWT carrying the user's role. Invalid credentials return `401` after a short delay. No prior authentication required.

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
*   **Description:** Triggers port scavenging, YAML schema verification, LiteLLM cache cleaning, and dependency verification. Also audits the enterprise dependency inventory in plan-only mode: missing dependencies are reported to `generated/repair-report.json` with their remediation strategy, but installs are never executed from the API (they require interactive console consent via `Manage.bat repair`).

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
