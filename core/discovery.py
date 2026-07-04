# core/discovery.py
# System hardware, tooling, and LLM ecosystem discovery engine for AIRM

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def run_powershell_cmd(cmd):
    """Run a PowerShell command and return the trimmed output or empty string."""
    try:
        # Using -NoProfile and -NonInteractive for speed and isolation
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception:
        return ""

def _cpu_name_posix():
    """CPU model name on macOS/Linux."""
    try:
        if platform.system() == "Darwin":
            res = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        else:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine() or "Unknown CPU"


def _parse_nvidia_smi_gpus(output):
    """Parse `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`."""
    gpus = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                vram_gb = round(float(parts[1]) / 1024, 2)  # MiB -> GB
            except ValueError:
                vram_gb = 0.0
            gpus.append({"name": parts[0], "vram_gb": vram_gb})
    return gpus


def _gpus_from_nvidia_smi():
    """Query NVIDIA GPUs directly. Works on all platforms and, unlike WMI
    AdapterRAM (a uint32 that overflows above 4GB), reports true VRAM."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
        )
        if res.returncode == 0:
            return _parse_nvidia_smi_gpus(res.stdout)
    except Exception:
        pass
    return []


def discover_hardware():
    """Discover hardware specs (psutil + nvidia-smi everywhere; CIM/WMI on Windows, sysfs/sysctl on POSIX)."""
    specs = {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": "Unknown CPU",
        "ram_gb": 0.0,
        "gpus": [],
        "disk": {"total_gb": 0.0, "free_gb": 0.0},
        "cuda": "Not Detected"
    }

    # 1. RAM and disk via psutil (cross-platform, already a core dependency)
    try:
        import psutil
        specs["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 2)
        du = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
        specs["disk"] = {
            "total_gb": round(du.total / (1024**3), 2),
            "free_gb": round(du.free / (1024**3), 2),
        }
    except Exception:
        pass

    # 2. CPU name
    if platform.system() == "Windows":
        cpu_name = run_powershell_cmd("(Get-CimInstance Win32_Processor).Name")
        if cpu_name:
            specs["cpu"] = cpu_name
    else:
        specs["cpu"] = _cpu_name_posix()

    # 3. GPUs: nvidia-smi first (accurate VRAM), then platform-specific fill-in
    specs["gpus"] = _gpus_from_nvidia_smi()
    seen_names = {g["name"] for g in specs["gpus"]}
    if platform.system() == "Windows":
        # CIM adds non-NVIDIA controllers (Intel/AMD iGPUs etc.)
        gpu_json = run_powershell_cmd(
            "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"
        )
        if gpu_json:
            try:
                data = json.loads(gpu_json)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = item.get("Name", "Unknown Controller")
                    if name in seen_names:
                        continue
                    vram_bytes = item.get("AdapterRAM", 0) or 0
                    # AdapterRAM is uint32: negative/overflowed values are unreliable
                    if isinstance(vram_bytes, int) and vram_bytes < 0:
                        vram_bytes = 0
                    specs["gpus"].append({
                        "name": name,
                        "vram_gb": round(vram_bytes / (1024**3), 2),
                    })
            except Exception:
                names = run_powershell_cmd("(Get-CimInstance Win32_VideoController).Name")
                if names:
                    for name in names.splitlines():
                        if name.strip() not in seen_names:
                            specs["gpus"].append({"name": name.strip(), "vram_gb": 0.0})
    elif not specs["gpus"] and platform.system() == "Darwin" and platform.machine() == "arm64":
        # Apple Silicon: unified memory — the GPU shares system RAM
        specs["gpus"].append({"name": "Apple Silicon (Metal)", "vram_gb": specs["ram_gb"]})

    # 4. CUDA Check
    # Try nvcc compiler version
    try:
        res = subprocess.run(["nvcc", "--version"], capture_output=True, text=True)
        if res.returncode == 0:
            m = re.search(r"release (\d+\.\d+)", res.stdout)
            if m:
                specs["cuda"] = f"CUDA v{m.group(1)} (nvcc)"
    except Exception:
        pass

    if specs["cuda"] == "Not Detected":
        # Check nvidia-smi
        try:
            res = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
            if res.returncode == 0:
                m = re.search(r"CUDA Version:\s+(\d+\.\d+)", res.stdout)
                if m:
                    specs["cuda"] = f"CUDA v{m.group(1)} (nvidia-smi)"
        except Exception:
            pass

    if specs["cuda"] == "Not Detected":
        cuda_path = os.environ.get("CUDA_PATH")
        if cuda_path:
            m = re.search(r"v(\d+\.\d+)", cuda_path)
            specs["cuda"] = f"CUDA v{m.group(1)} (env)" if m else "CUDA Present (env)"

    return specs

def get_hardware_recommendations(specs):
    """Translate hardware specifications into dynamic system capabilities and suggestions."""
    ram = specs["ram_gb"]

    # Calculate total VRAM from any NVIDIA controller
    nvidia_vram = 0.0
    has_nvidia = False
    for gpu in specs["gpus"]:
        name = gpu["name"].lower()
        if "nvidia" in name or "geforce" in name or "rtx" in name or "quadro" in name or "tesla" in name:
            has_nvidia = True
            nvidia_vram = max(nvidia_vram, gpu["vram_gb"])

    # Determine Tier
    if has_nvidia and nvidia_vram >= 15.0 and ram >= 31.0:
        tier = "Ultra"
        rec = "Your workstation has excellent hardware specs. You can run large models locally (e.g. 70B parameter models or 32B MoE models) with full GPU acceleration."
    elif has_nvidia and nvidia_vram >= 7.0 and ram >= 15.0:
        tier = "High"
        rec = "Your workstation is suitable for mid-sized local models (e.g., Llama 3 8B, Qwen 2.5 7B/14B) with complete GPU acceleration and fast response times."
    elif ram >= 15.0:
        tier = "Medium"
        if has_nvidia:
            rec = f"Your system has an NVIDIA GPU with {nvidia_vram}GB VRAM. It can run smaller models locally (e.g., Llama 3 3B, Qwen 2.5 3B) with GPU acceleration, or larger models using CPU fallback."
        else:
            rec = "Your system has decent RAM but lacks a dedicated NVIDIA GPU. You can run small models locally (up to 7B) using Ollama's CPU execution, but response times will be slow. We recommend using Cloud API providers (Gemini, Groq, SambaNova) for fast response times."
    else:
        tier = "Low"
        rec = "Your system has low RAM and no suitable GPU. Running local models is not recommended. You should rely on Cloud API Providers (Gemini, Groq, SambaNova) which process queries on their remote servers with zero local overhead."

    return {
        "tier": tier,
        "recommendation": rec,
        "has_nvidia": has_nvidia,
        "max_local_param_size": "70B" if tier == "Ultra" else "14B" if tier == "High" else "3B" if tier == "Medium" else "None"
    }

def discover_tools():
    """Detect local paths of required installation tools."""
    tools = {}
    user_home = os.path.expanduser("~")

    for tool in ["git", "python", "node", "npm", "uv", "ollama"]:
        path = shutil.which(tool)
        if path:
            tools[tool] = path
        else:
            # Check common Windows installation paths
            if tool == "python":
                for p in ["C:\\Python314\\python.exe", "C:\\Python313\\python.exe", "C:\\Python312\\python.exe", "C:\\Python311\\python.exe"]:
                    if os.path.exists(p):
                        tools[tool] = p
                        break
            elif tool == "node" and os.path.exists("C:\\Program Files\\nodejs\\node.exe"):
                tools[tool] = "C:\\Program Files\\nodejs\\node.exe"
            elif tool == "npm" and os.path.exists("C:\\Program Files\\nodejs\\npm.cmd"):
                tools[tool] = "C:\\Program Files\\nodejs\\npm.cmd"
            elif tool == "uv":
                p = os.path.join(user_home, ".local", "bin", "uv.exe")
                if os.path.exists(p):
                    tools[tool] = p
            elif tool == "ollama":
                for p in [os.path.join(os.environ.get("LocalAppData", ""), "Programs", "Ollama", "ollama.exe"), "C:\\Program Files\\Ollama\\ollama.exe"]:
                    if os.path.exists(p):
                        tools[tool] = p
                        break

    return tools

def load_litellm_catalog():
    """Dynamically load and group the LiteLLM model cost database."""
    catalog = {}
    try:
        import litellm
        if hasattr(litellm, "model_cost"):
            db = litellm.model_cost
        else:
            # Fallback to local package backup JSON file
            litellm_dir = os.path.dirname(litellm.__file__)
            json_path = os.path.join(litellm_dir, "model_prices_and_context_window_backup.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
            else:
                db = {}
    except Exception:
        db = {}

    # Group by standard provider keys
    # Map litellm providers to user-facing provider tags
    provider_map = {
        "gemini": "gemini",
        "google": "gemini",
        "groq": "groq",
        "sambanova": "sambanova",
        "cerebras": "cerebras",
        "openrouter": "openrouter",
        "mistral": "mistral",
        "together": "together",
        "together_ai": "together",
        "fireworks": "fireworks",
        "fireworks_ai": "fireworks",
        "deepseek": "deepseek",
        "moonshot": "moonshot",
        "ollama": "ollama",
        "openai": "openai",
        "anthropic": "anthropic"
    }

    for model_key, spec in db.items():
        # Get provider
        litellm_provider = spec.get("litellm_provider", "").lower()
        if not litellm_provider:
            # Try to infer provider from key prefix (e.g. gemini/ or groq/)
            if "/" in model_key:
                prefix = model_key.split("/")[0].lower()
                litellm_provider = prefix

        provider = provider_map.get(litellm_provider)
        if not provider:
            continue

        if provider not in catalog:
            catalog[provider] = []

        # Clean up model entry
        # Context window: check max_input_tokens or max_tokens
        context = spec.get("max_input_tokens") or spec.get("max_tokens") or 4096
        max_output = spec.get("max_output_tokens") or spec.get("max_tokens") or 4096

        # Human readable clean name
        name = model_key
        if "/" in name:
            name = name.split("/")[-1]
        name = name.replace("-", " ").replace("_", " ").title()

        # Capability flags
        capabilities = []
        if spec.get("supports_vision"):
            capabilities.append("Vision")
        if spec.get("supports_function_calling") or spec.get("supports_parallel_function_calling"):
            capabilities.append("Function Calling")
        if spec.get("supports_reasoning"):
            capabilities.append("Reasoning")
        if spec.get("supports_response_schema"):
            capabilities.append("Structured Output")

        # Token cost
        input_cost = spec.get("input_cost_per_token", 0.0) * 1e6 # cost per 1M tokens
        output_cost = spec.get("output_cost_per_token", 0.0) * 1e6

        catalog[provider].append({
            "id": model_key,
            "name": name,
            "context_window": context,
            "max_output_tokens": max_output,
            "capabilities": capabilities,
            "mode": spec.get("mode", "chat"),
            "cost_per_1m_input_usd": round(input_cost, 4),
            "cost_per_1m_output_usd": round(output_cost, 4)
        })

    return catalog

def get_ollama_models(api_base):
    """Query local Ollama instance for installed models."""
    import urllib.request
    try:
        url = f"{api_base.rstrip('/')}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=1.5) as response:
            data = json.loads(response.read().decode())
            return data.get('models', [])
    except Exception:
        return []

def evaluate_ollama_suitability(ollama_models, specs):
    """Evaluate downloaded Ollama models against local hardware specifications."""
    evaluated = []

    # Calculate total memory budget (NVIDIA VRAM is premium, RAM is backup)
    vram_gb = 0.0
    for gpu in specs["gpus"]:
        name = gpu["name"].lower()
        if "nvidia" in name or "rtx" in name or "gtx" in name or "geforce" in name:
            vram_gb = max(vram_gb, gpu["vram_gb"])

    ram_gb = specs["ram_gb"]

    for m in ollama_models:
        name = m.get("name", "unknown")
        details = m.get("details", {})
        parameter_size = details.get("parameter_size", "")

        # Infer parameter count (e.g. "8.0B" or "70B")
        param_gb = 0.0
        m_size = re.search(r"(\d+(\.\d+)?)B", parameter_size, re.IGNORECASE)
        if m_size:
            param_gb = float(m_size.group(1))
        else:
            # Try to infer parameter size from model tag name (e.g. llama3:8b)
            tag_size = re.search(r"(\d+(\.\d+)?)b", name, re.IGNORECASE)
            if tag_size:
                param_gb = float(tag_size.group(1))

        # Estimate RAM needed in GB (highly quantized 4-bit models typically need ~0.7GB RAM per 1B parameters + 1-2GB overhead)
        required_ram = (param_gb * 0.7) + 1.5 if param_gb > 0 else 4.0

        # Decide suitability
        if param_gb == 0:
            suitability = "Unknown Requirements"
            status = "unknown"
            comment = "Unable to estimate size."
        elif vram_gb >= required_ram:
            suitability = "Excellent (Accelerated)"
            status = "excellent"
            comment = f"Fits comfortably inside VRAM ({round(required_ram, 1)}GB required vs {vram_gb}GB VRAM). Fully GPU accelerated."
        elif (vram_gb + ram_gb) >= required_ram:
            if vram_gb > 0:
                suitability = "Partial Acceleration"
                status = "partial"
                comment = "Exceeds dedicated VRAM but fits in system RAM. Will run at moderate speeds using CPU/GPU offloading."
            else:
                suitability = "Runs slowly on CPU"
                status = "cpu"
                comment = f"Requires {round(required_ram, 1)}GB memory. System lacks NVIDIA GPU, will run slowly on CPU."
        else:
            suitability = "Insufficient Memory"
            status = "failed"
            comment = f"Requires {round(required_ram, 1)}GB memory, which exceeds system resources."

        evaluated.append({
            "name": name,
            "parameter_size": parameter_size or f"{param_gb}B" if param_gb > 0 else "Unknown",
            "size_bytes": m.get("size", 0),
            "required_ram_gb": round(required_ram, 1),
            "suitability": suitability,
            "status": status,
            "comment": comment
        })

    return evaluated

# --- Enterprise dependency inventory ---

_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)*[\w.\-+]*)")

# (name, category, version args) — path resolved via discover_tools()/shutil.which
_DEPENDENCY_PROBES = [
    ("git", "tool", ["--version"]),
    ("python", "runtime", ["--version"]),
    ("node", "runtime", ["--version"]),
    ("npm", "tool", ["--version"]),
    ("uv", "tool", ["--version"]),
    ("java", "runtime", ["-version"]),
    ("docker", "container", ["--version"]),
    ("ollama", "ai_runtime", ["--version"]),
]


def _probe_version(args, timeout=10):
    """Run a version command and return the first version-looking token, or ''."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        # java prints to stderr; wsl prints UTF-16 (null bytes under a cp1252 decode)
        out = ((res.stdout or "") + (res.stderr or "")).replace("\x00", "")
        m = _VERSION_RE.search(out)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _gpu_vendor(name):
    """Classify a video controller name into a GPU vendor tag."""
    n = name.lower()
    if any(k in n for k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla")):
        return "nvidia"
    if any(k in n for k in ("amd", "radeon")):
        return "amd"
    if "intel" in n:
        return "intel"
    if "apple" in n:
        return "apple"
    return "other"


def _detect_virtualization():
    """Return (status, details) for hypervisor availability on this platform."""
    system = platform.system()
    try:
        if system == "Windows":
            out = run_powershell_cmd("(Get-CimInstance Win32_ComputerSystem).HypervisorPresent")
            return ("present" if out.strip().lower() == "true" else "missing", "Hyper-V hypervisor")
        if system == "Darwin":
            res = subprocess.run(["sysctl", "-n", "kern.hv_support"], capture_output=True, text=True)
            return ("present" if res.stdout.strip() == "1" else "missing", "Hypervisor.framework")
        if os.path.exists("/dev/kvm"):
            return ("present", "/dev/kvm")
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            flags = f.read()
        return ("present" if ("vmx" in flags or "svm" in flags) else "missing", "cpu virtualization flags")
    except Exception:
        return ("unknown", "")


def discover_dependency_inventory(specs=None):
    """Build the enterprise dependency inventory: runtimes, SDKs, drivers, and
    platform features, each reported as present/missing with version and path."""
    specs = specs or discover_hardware()
    tools = discover_tools()
    items = []

    def add(name, category, status, version="", path="", details=""):
        items.append({
            "name": name, "category": category, "status": status,
            "version": version, "path": path, "details": details,
        })

    # Command-line runtimes and tools
    for name, category, ver_args in _DEPENDENCY_PROBES:
        path = tools.get(name) or shutil.which(name)
        if path:
            add(name, category, "present", _probe_version([path, *ver_args]), path)
        else:
            add(name, category, "missing")

    # NVIDIA driver (nvidia-smi reports the driver version directly)
    smi = shutil.which("nvidia-smi")
    driver_ver = _probe_version([smi, "--query-gpu=driver_version", "--format=csv,noheader"]) if smi else ""
    add("nvidia-driver", "gpu_driver", "present" if smi else "missing", driver_ver, smi or "")

    # CUDA toolkit/runtime (already probed by discover_hardware)
    cuda = specs.get("cuda", "Not Detected")
    cuda_m = _VERSION_RE.search(cuda)
    add("cuda", "gpu_sdk", "present" if cuda != "Not Detected" else "missing",
        cuda_m.group(1) if cuda_m else "", os.environ.get("CUDA_PATH", ""), cuda)

    # ROCm / HIP
    rocm_path = shutil.which("rocm-smi") or shutil.which("hipcc") or (
        "/opt/rocm" if os.path.isdir("/opt/rocm") else "")
    rocm_ver = _probe_version([rocm_path, "--version"]) if rocm_path and os.path.isfile(rocm_path) else ""
    add("rocm", "gpu_sdk", "present" if rocm_path else "missing", rocm_ver, rocm_path)

    # WSL (Windows only)
    if platform.system() == "Windows":
        wsl = shutil.which("wsl")
        add("wsl", "platform", "present" if wsl else "missing",
            _probe_version([wsl, "--version"]) if wsl else "", wsl or "")

    # Hardware virtualization
    virt_status, virt_details = _detect_virtualization()
    add("virtualization", "platform", virt_status, details=virt_details)

    present = sum(1 for i in items if i["status"] == "present")
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": {"os": specs.get("os", ""), "machine": platform.machine()},
        "hardware": specs,
        "gpu_vendors": sorted({_gpu_vendor(g["name"]) for g in specs.get("gpus", [])}),
        "items": items,
        "summary": {"present": present, "missing": len(items) - present},
    }


def run_all_discovery(settings_path):
    """Aggregate all discovery findings into a single data structure."""
    settings = {}
    if os.path.exists(settings_path):
        try:
            import yaml
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = yaml.safe_load(f) or {}
        except Exception:
            pass

    api_base = "http://127.0.0.1:11434"
    if settings:
        api_base = settings.get("ollama", {}).get("api_base", api_base)

    specs = discover_hardware()
    recs = get_hardware_recommendations(specs)
    tools = discover_tools()

    # Query Ollama
    ollama_models = get_ollama_models(api_base)
    evaluated_ollama = evaluate_ollama_suitability(ollama_models, specs)

    # Load LiteLLM metadata
    catalog = load_litellm_catalog()

    return {
        "specs": specs,
        "recommendations": recs,
        "tools": tools,
        "ollama": {
            "online": len(ollama_models) > 0 or (shutil.which("ollama") is not None),
            "api_connected": len(ollama_models) > 0,
            "models": evaluated_ollama
        },
        "litellm_catalog": catalog
    }

if __name__ == "__main__":
    # Test execution
    res = run_all_discovery(os.path.join(os.path.dirname(__file__), "..", "OpenClawManager", "settings.yaml"))
    import sys
    sys.stdout.write(json.dumps(res, indent=2))
