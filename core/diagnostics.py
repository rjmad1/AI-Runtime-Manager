# core/diagnostics.py
# Endpoint benchmarking and health report generation for AIRM.

import html
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List

from .config import (
    GENERATED_DIR,
    MODELS_PATH,
    PROVIDERS_PATH,
    SETTINGS_PATH,
    get_windows_env,
    load_yaml,
    log,
)
from .process import get_pids_on_port


class LiteLLMOfflineError(RuntimeError):
    """Raised when diagnostics cannot run because the LiteLLM proxy is offline."""

def _run_benchmarks(active_models: List[Dict[str, Any]], litellm_port: int, litellm_key: str, diagnostics: Dict[str, Any]) -> None:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {litellm_key}",
    }

    for am in active_models:
        model_id: str = am.get("id", "")
        friendly_name: str = am.get("name", "")
        provider: str = am.get("provider", "")

        log("INFO", f"Benchmarking latency for {friendly_name} ({model_id})...")

        body = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Respond with only one word: test"}],
            "max_tokens": 3,
        }

        start = time.perf_counter()
        success = False
        latency = 0
        error_msg = ""
        response_text = ""

        try:
            req = urllib.request.Request(
                f"http://localhost:{litellm_port}/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12.0) as res:
                latency = int((time.perf_counter() - start) * 1000)
                res_data = json.loads(res.read().decode())
                response_text = res_data["choices"][0]["message"]["content"].strip()
                success = True
                log("SUCCESS", f"  Response returned in {latency}ms: '{response_text}'")
        except urllib.error.HTTPError as e:
            latency = int((time.perf_counter() - start) * 1000)
            try:
                error_msg = json.loads(e.read().decode())["error"]["message"]
            except Exception:
                error_msg = str(e)
            log("ERROR", f"  Request failed: {error_msg}")
        except Exception as e:
            latency = int((time.perf_counter() - start) * 1000)
            error_msg = str(e)
            log("ERROR", f"  Request failed: {error_msg}")

        diagnostics["models"].append({
            "id": model_id,
            "name": friendly_name,
            "provider": provider,
            "success": success,
            "latency_ms": latency if success else None,
            "response": response_text,
            "error": error_msg,
        })


def cmd_diagnose() -> Dict[str, Any]:
    """Run latency benchmarks against all configured model endpoints."""
    log("INFO", "Running endpoint connectivity and speed benchmarks...")

    from . import discovery

    settings = load_yaml(SETTINGS_PATH)
    providers = load_yaml(PROVIDERS_PATH)
    models_reg = load_yaml(MODELS_PATH)

    litellm_port: int = settings.get("litellm", {}).get("port", 4000)
    litellm_key: str = settings.get("litellm", {}).get("api_key", "sk-litellm-key")

    sys_details = discovery.run_all_discovery(SETTINGS_PATH)
    tools = sys_details["tools"]
    specs = sys_details["specs"]

    diagnostics: Dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "os": specs["os"],
        "gpu": " / ".join([g["name"] for g in specs["gpus"]]) if specs["gpus"] else "CPU Only",
        "tools": tools,
        "models": [],
    }

    l_pids = get_pids_on_port(litellm_port)
    if not l_pids:
        log("ERROR", f"LiteLLM Proxy is OFFLINE on port {litellm_port}. Cannot execute diagnostics.")
        raise LiteLLMOfflineError(
            f"LiteLLM Proxy is offline on port {litellm_port}. Start the services and retry."
        )

    # Collect active models
    active_models: List[Dict[str, Any]] = []
    for m in models_reg.get("models", []):
        provider = m.get("provider")
        p_cfg = providers.get(provider, {})
        if isinstance(p_cfg, dict) and p_cfg.get("enabled", False) and get_windows_env(p_cfg.get("env_var")):
            active_models.append(m)

    ollama_api: str = settings.get("ollama", {}).get("api_base", "http://127.0.0.1:11434")
    ollama_models = discovery.get_ollama_models(ollama_api)
    for om in ollama_models:
        om_name = om.get("name")
        active_models.append({
            "id": f"ollama/{om_name}",
            "name": f"{om_name} (Ollama)",
            "provider": "ollama",
        })

    _run_benchmarks(active_models, litellm_port, litellm_key, diagnostics)

    generate_diagnostic_reports(diagnostics)
    return diagnostics


def _generate_markdown_report(diagnostics: Dict[str, Any], md_path: str) -> None:
    md = [
        "# AIRM Diagnostics & Connectivity Report",
        f"\n**Execution Timestamp:** {diagnostics['timestamp']}",
        f"**Operating System:** {diagnostics['os']}",
        f"**Video Controller:** {diagnostics['gpu']}\n",
        "## Dependency Audit",
        "| Package | Registry Status | Target Filepath |",
        "| :--- | :--- | :--- |",
    ]
    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        status = "FOUND" if tool in diagnostics["tools"] else "MISSING"
        path = diagnostics["tools"].get(tool, "N/A")
        md.append(f"| {tool.upper()} | {status} | `{path}` |")

    md.append("\n## Endpoint Latency registry")
    md.append("| Provider / Model ID | Status | Latency (ms) | Output Summary / Error |")
    md.append("| :--- | :--- | :--- | :--- |")

    for m in diagnostics["models"]:
        status = "HEALTHY" if m["success"] else "FAILED"
        latency = f"{m['latency_ms']} ms" if m["success"] else "N/A"
        desc = f"Returned: '{m['response']}'" if m["success"] else f"Error: {m['error']}"
        md.append(f"| {m['name']} (`{m['id']}`) | {status} | {latency} | {desc} |")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

def _generate_html_report(diagnostics: Dict[str, Any], html_path: str) -> None:
    _e = html.escape  # shorthand

    html_lines = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "  <meta charset='UTF-8'>",
        "  <title>AIRM Diagnostics Console</title>",
        "  <link href='https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap' rel='stylesheet'>",
        "  <style>",
        "    :root { --bg: #0f172a; --card: #1e293b; --border: #334155; --accent: #3b82f6; --success: #10b981; --error: #ef4444; --text: #f8fafc; --muted: #94a3b8; }",
        "    * { box-sizing: border-box; margin: 0; padding: 0; }",
        "    body { font-family: 'Outfit', sans-serif; background-color: var(--bg); color: var(--text); padding: 3rem 1.5rem; line-height: 1.6; }",
        "    .container { max-width: 1000px; margin: 0 auto; }",
        "    header { margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; }",
        "    h1 { font-size: 2.25rem; font-weight: 700; background: linear-gradient(to right, #60a5fa, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }",
        "    h2 { margin: 2rem 0 1rem; }",
        "    .meta-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; margin-bottom: 2.5rem; }",
        "    .meta-card { background: var(--card); border: 1px solid var(--border); padding: 1.25rem; border-radius: 12px; }",
        "    .meta-label { font-size: 0.85rem; color: var(--muted); text-transform: uppercase; margin-bottom: 0.25rem; }",
        "    .meta-value { font-size: 1.15rem; font-weight: 600; }",
        "    table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-bottom: 2.5rem; }",
        "    th, td { padding: 1rem 1.25rem; text-align: left; }",
        "    th { background: #1e293b; font-weight: 600; border-bottom: 1px solid var(--border); }",
        "    tr:not(:last-child) { border-bottom: 1px solid var(--border); }",
        "    .badge { display: inline-block; padding: 0.2rem 0.6rem; font-size: 0.75rem; font-weight: 600; border-radius: 9999px; text-transform: uppercase; }",
        "    .badge-found { background: rgba(16, 185, 129, 0.15); color: var(--success); }",
        "    .badge-missing { background: rgba(239, 68, 68, 0.15); color: var(--error); }",
        "    .model-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }",
        "    .model-card { background: var(--card); border: 1px solid var(--border); padding: 1.5rem; border-radius: 16px; transition: transform 0.2s; }",
        "    .model-card:hover { transform: translateY(-2px); border-color: var(--accent); }",
        "    .model-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }",
        "    .model-name { font-size: 1.2rem; font-weight: 600; }",
        "    .model-id { font-size: 0.8rem; color: var(--muted); font-family: monospace; }",
        "    .latency { font-size: 1.5rem; font-weight: 700; color: var(--accent); margin: 0.5rem 0; }",
        "    .error-box { background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); color: #fca5a5; padding: 0.75rem; border-radius: 8px; font-size: 0.8rem; font-family: monospace; word-break: break-all; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <div class='container'>",
        "    <header>",
        "      <h1>AIRM Integrity Diagnostics Report</h1>",
        "      <p style='color: var(--muted); margin-top: 0.25rem;'>Workstation Endpoint Benchmarks</p>",
        "    </header>",
        "    <div class='meta-grid'>",
        f"      <div class='meta-card'><div class='meta-label'>Timestamp</div><div class='meta-value'>{_e(diagnostics['timestamp'])}</div></div>",
        f"      <div class='meta-card'><div class='meta-label'>OS Details</div><div class='meta-value'>{_e(diagnostics['os'])}</div></div>",
        f"      <div class='meta-card'><div class='meta-label'>Video Controllers</div><div class='meta-value'>{_e(diagnostics['gpu'])}</div></div>",
        "    </div>",
        "    <h2>Prerequisite Software Checks</h2>",
        "    <table>",
        "      <thead><tr><th>Dependency</th><th>Availability</th><th>Filepath</th></tr></thead>",
        "      <tbody>",
    ]
    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        status = "FOUND" if tool in diagnostics["tools"] else "MISSING"
        badge = "badge-found" if tool in diagnostics["tools"] else "badge-missing"
        path = _e(diagnostics["tools"].get(tool, "N/A"))
        html_lines.append(
            f"        <tr><td><strong>{tool.upper()}</strong></td>"
            f"<td><span class='badge {badge}'>{status}</span></td>"
            f"<td><code>{path}</code></td></tr>"
        )

    html_lines.extend([
        "      </tbody>",
        "    </table>",
        "    <h2>Provider Latency Benchmarks</h2>",
        "    <div class='model-grid'>",
    ])
    for m in diagnostics["models"]:
        badge = "badge-found" if m["success"] else "badge-missing"
        status_txt = "Healthy" if m["success"] else "Failed"
        latency_txt = f"{m['latency_ms']} ms" if m["success"] else "Offline"

        html_lines.append(
            f"      <div class='model-card'>"
            f"<div class='model-header'><div>"
            f"<div class='model-name'>{_e(m['name'])}</div>"
            f"<div class='model-id'>{_e(m['id'])}</div>"
            f"</div><span class='badge {badge}'>{status_txt}</span></div>"
            f"<div class='latency'>{_e(latency_txt)}</div>"
        )
        if m["success"]:
            html_lines.append(
                f"        <div style='font-size: 0.85rem; color: var(--muted)'>Response: "
                f"<span style='color: var(--text); font-style: italic'>\"{_e(m['response'])}\"</span></div>"
            )
        else:
            html_lines.append(f"        <div class='error-box'>{_e(m['error'])}</div>")
        html_lines.append("      </div>")

    html_lines.extend([
        "    </div>",
        "  </div>",
        "</body>",
        "</html>",
    ])

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_lines))

def generate_diagnostic_reports(diagnostics: Dict[str, Any]) -> None:
    """Generate HTML and Markdown health reports with proper output escaping."""
    md_path = os.path.join(GENERATED_DIR, "health-report.md")
    html_path = os.path.join(GENERATED_DIR, "health-report.html")

    _generate_markdown_report(diagnostics, md_path)
    _generate_html_report(diagnostics, html_path)
    log("SUCCESS", "Diagnostic health reports generated: health-report.md and health-report.html")
