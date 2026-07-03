# tests/test_integration.py
# Integration tests for AIRM service lifecycle.
# These tests verify cross-module interactions with mocked external dependencies.

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


class TestServiceLifecycle:
    """Integration tests for service start/stop/status lifecycle."""

    def test_status_reports_offline_when_no_services(self, tmp_path, monkeypatch):
        """cmd_status should report OFFLINE when no services are running."""
        config_dir = tmp_path / "OpenClawManager"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text(
            "litellm:\n  port: 49999\noclaw:\n  port: 49998\n"
        )

        generated_dir = tmp_path / "generated"
        generated_dir.mkdir()
        (generated_dir / "services.json").write_text('{"litellm": null, "openclaw": null}')

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        monkeypatch.setattr("config.ROOT_DIR", str(tmp_path))
        monkeypatch.setattr("config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("config.GENERATED_DIR", str(generated_dir))
        monkeypatch.setattr("config.LOGS_DIR", str(logs_dir))
        monkeypatch.setattr("config.SETTINGS_PATH", str(config_dir / "settings.yaml"))
        monkeypatch.setattr("config.SERVICES_STATE_PATH", str(generated_dir / "services.json"))
        monkeypatch.setattr("config.LOG_FILE", str(logs_dir / "installer.log"))

        from process import cmd_status
        result = cmd_status()

        assert result["litellm"]["status"] == "OFFLINE"
        assert result["openclaw"]["status"] == "OFFLINE"

    def test_services_state_persistence(self, tmp_path, monkeypatch):
        """save_services_state should persist PIDs to services.json."""
        generated_dir = tmp_path / "generated"
        generated_dir.mkdir()
        state_path = str(generated_dir / "services.json")

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        monkeypatch.setattr("config.SERVICES_STATE_PATH", state_path)
        monkeypatch.setattr("config.LOG_FILE", str(logs_dir / "installer.log"))

        from process import save_services_state, load_services_state

        save_services_state({"litellm": 12345, "openclaw": 67890})
        loaded = load_services_state()

        assert loaded["litellm"] == 12345
        assert loaded["openclaw"] == 67890


class TestConfigureCompilation:
    """Integration tests for configuration compilation pipeline."""

    def test_configure_creates_litellm_config(self, tmp_path, monkeypatch):
        """cmd_configure should produce a valid LiteLLM config.yaml."""
        config_dir = tmp_path / "OpenClawManager"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text(
            "litellm:\n  port: 4000\n  api_key: sk-test-key\n  drop_params: true\n"
            "  set_verbose: false\n  routing_strategy: latency-based-routing\n"
            "  num_retries: 3\n  request_timeout: 30\n"
            "openclaw:\n  port: 18789\n  config_dir: ''\n"
            "ollama:\n  enabled: false\n"
        )
        (config_dir / "providers.yaml").write_text(
            "gemini:\n  enabled: false\n  env_var: GEMINI_API_KEY\n  info: Test\n"
        )
        (config_dir / "models.yaml").write_text(
            "models:\n  - id: test-model\n    name: Test Model\n    provider: gemini\n"
            "    litellm_model: gemini/test\n    context_window: 4096\n    max_tokens: 4096\n"
        )

        generated_dir = tmp_path / "generated"
        generated_dir.mkdir()
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        monkeypatch.setattr("config.ROOT_DIR", str(tmp_path))
        monkeypatch.setattr("config.CORE_DIR", str(tmp_path / "core"))
        monkeypatch.setattr("config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("config.GENERATED_DIR", str(generated_dir))
        monkeypatch.setattr("config.LOGS_DIR", str(logs_dir))
        monkeypatch.setattr("config.SETTINGS_PATH", str(config_dir / "settings.yaml"))
        monkeypatch.setattr("config.PROVIDERS_PATH", str(config_dir / "providers.yaml"))
        monkeypatch.setattr("config.MODELS_PATH", str(config_dir / "models.yaml"))
        monkeypatch.setattr("config.LITELLM_CONFIG_PATH", str(generated_dir / "config.yaml"))
        monkeypatch.setattr("config.OPENCLAW_CONFIG_PATH", str(generated_dir / "openclaw.json"))
        monkeypatch.setattr("config.LOG_FILE", str(logs_dir / "installer.log"))

        # Mock discovery to avoid PowerShell calls
        mock_discovery = MagicMock()
        mock_discovery.run_all_discovery.return_value = {
            "specs": {"os": "Windows", "cpu": "Test", "ram_gb": 16, "gpus": [], "disk": {}},
            "tools": {"python": "python.exe"},
            "recommendations": {"tier": "medium", "recommendation": "Test"},
            "ollama": {"online": False, "models": []},
        }
        mock_discovery.get_ollama_models.return_value = []
        monkeypatch.setitem(sys.modules, "discovery", mock_discovery)

        from config import cmd_configure
        cmd_configure()

        litellm_config_path = str(generated_dir / "config.yaml")
        assert os.path.exists(litellm_config_path)
