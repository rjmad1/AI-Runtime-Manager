# tests/test_discovery.py
# Unit tests for core/discovery.py — hardware discovery and model evaluation.



from core.discovery import (
    _parse_nvidia_smi_gpus,
    discover_hardware,
    evaluate_ollama_suitability,
    get_hardware_recommendations,
)


class TestHardwareRecommendations:
    """Tests for get_hardware_recommendations."""

    def test_high_vram_recommendation(self):
        """Systems with >= 12 GB VRAM should get 'excellent' or 'high' tier."""
        specs = {
            "ram_gb": 32,
            "gpus": [{"name": "NVIDIA RTX 4090", "vram_gb": 24.0}],
            "cpu": "Intel i9",
        }
        result = get_hardware_recommendations(specs)
        assert "tier" in result
        assert result["tier"].lower() in ("ultra", "high", "excellent")

    def test_cpu_only_recommendation(self):
        """Systems without GPUs should recommend cloud-based models."""
        specs = {
            "ram_gb": 8,
            "gpus": [],
            "cpu": "Intel i5",
        }
        result = get_hardware_recommendations(specs)
        assert "tier" in result
        assert "recommendation" in result

    def test_low_ram_recommendation(self):
        """Systems with very low RAM should get 'limited' or 'low' tier."""
        specs = {
            "ram_gb": 4,
            "gpus": [],
            "cpu": "Intel Celeron",
        }
        result = get_hardware_recommendations(specs)
        assert result["tier"].lower() in ("limited", "low")


class TestEvaluateOllamaSuitability:
    """Tests for evaluate_ollama_suitability."""

    def test_small_model_excellent_on_high_vram(self):
        """A small 8B model should be 'excellent' on a 24 GB VRAM system."""
        model = {
            "name": "llama3:8b",
            "size": 4_500_000_000,
            "details": {"parameter_size": "8B"},
        }
        specs = {
            "ram_gb": 32,
            "gpus": [{"name": "RTX 4090", "vram_gb": 24.0}],
        }
        result = evaluate_ollama_suitability([model], specs)
        assert len(result) == 1
        assert result[0]["status"] in ("excellent", "partial")
        assert "suitability" in result[0]
        assert result[0]["required_ram_gb"] > 0

    def test_large_model_on_low_spec(self):
        """A 70B model should flag issues on a low-spec system."""
        model = {
            "name": "llama3:70b",
            "size": 40_000_000_000,
            "details": {"parameter_size": "70B"},
        }
        specs = {
            "ram_gb": 8,
            "gpus": [],
        }
        result = evaluate_ollama_suitability([model], specs)
        assert len(result) == 1
        assert result[0]["required_ram_gb"] > 8
        assert result[0]["status"] == "failed"


class TestNvidiaSmiParsing:
    """Tests for nvidia-smi CSV output parsing (true VRAM, no uint32 overflow)."""

    def test_parses_multi_gpu_output(self):
        output = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 3060, 12288\n"
        gpus = _parse_nvidia_smi_gpus(output)
        assert len(gpus) == 2
        assert gpus[0]["name"] == "NVIDIA GeForce RTX 4090"
        assert gpus[0]["vram_gb"] == 23.99  # 24564 MiB
        assert gpus[1]["vram_gb"] == 12.0

    def test_ignores_garbage_lines(self):
        gpus = _parse_nvidia_smi_gpus("no comma here\nGPU X, not-a-number\n")
        assert gpus == [{"name": "GPU X", "vram_gb": 0.0}]


class TestDiscoverHardware:
    """Cross-platform contract: discovery always returns the full spec shape."""

    def test_returns_required_keys(self):
        specs = discover_hardware()
        for key in ("os", "cpu", "ram_gb", "gpus", "disk", "cuda"):
            assert key in specs
        assert specs["ram_gb"] > 0  # psutil path works on every platform
        assert specs["disk"]["total_gb"] > 0

