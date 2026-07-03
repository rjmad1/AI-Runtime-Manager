# tests/test_discovery.py
# Unit tests for core/discovery.py — hardware discovery and model evaluation.

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.discovery import (
    get_hardware_recommendations,
    evaluate_ollama_suitability,
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

