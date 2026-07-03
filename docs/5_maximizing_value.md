# Maximizing Value from the AIRM Ecosystem

To derive maximum performance, stability, and utility from the AI Runtime Manager (AIRM), apply these advanced configurations and architectural best practices:

---

## 🏎️ 1. Fine-Tune Router Settings for Performance
In `OpenClawManager/settings.yaml`, customize the `litellm` router parameters to optimize request throughput and minimize latency:

*   **`routing_strategy`**:
    *   Set to `latency-based-routing` to automatically map queries to the fastest active provider.
    *   Set to `simple-shuffle` if you want to distribute requests evenly across identical model endpoints to bypass rate limits.
*   **`num_retries`**: Set to `3` or `4` to ensure transient API network failures are resolved without returning error codes to your front-end apps.
*   **`request_timeout`**: Tune this based on your models. If running slow reasoning models (like o1 or DeepSeek R1), increase to `60` or `120` seconds. For fast completion models (like Gemini 2.5 Flash), keep at `30` seconds to trigger fallbacks quickly if a node hangs.

```yaml
litellm:
  routing_strategy: "latency-based-routing"
  num_retries: 3
  request_timeout: 45
```

---

## 💾 2. Establish Automated Backups
AIRM includes an integrated zip backup and restore utility that packages your models registry, active keys, and configurations.
*   Run **`Manage.bat backup`** after validating a new set of API keys or configuring your local models.
*   AIRM compresses configuration profiles and verifies paths with security filters to prevent directory traversal vulnerabilities (Zip Slip).
*   Save the resulting backup files located in your configured `backup_dir` (default is `backups/`) to a secure corporate vault or cloud storage (e.g. OneDrive, Google Drive).

---

## 🦙 3. Leverage Local Model Quantization Specs
When using Ollama local models:
*   Use the **Local Ollama** tab in the visual dashboard to audit downloaded models.
*   Always check the **Suitability Status**. If a model displays **Excellent (Accelerated)**, it runs entirely within VRAM, delivering low latency. If it displays **Partial Acceleration** or **Runs slowly on CPU**, it will offload layers to system RAM, which significantly slows down tokens-per-second generation.
*   For CPU execution, prefer highly quantized models (e.g. 4-bit quantization, such as `llama3:8b-instruct-q4_K_M`) to decrease memory footprint and increase generation speed.

---

## 🛡️ 4. Keep API Keys Secure
*   **Never** hardcode or write raw API keys into configuration yaml files.
*   AIRM relies on Windows User Environment Variables to store credentials persistently.
*   To verify or rotate keys, always use the **API Provider Keys** dashboard in the visual browser wizard. This ensures that credential validation occurs before keys are committed to the Windows registry.
