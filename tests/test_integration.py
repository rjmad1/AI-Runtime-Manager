# tests/test_integration.py
# Integration tests for AIRM service lifecycle.
# These tests verify cross-module interactions with mocked external dependencies.

import os
import sys
from unittest.mock import MagicMock


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

        # core.process binds these names at import time, so patch them there
        monkeypatch.setattr("core.process.SETTINGS_PATH", str(config_dir / "settings.yaml"))
        monkeypatch.setattr("core.process.SERVICES_STATE_PATH", str(generated_dir / "services.json"))
        monkeypatch.setattr("core.config.LOG_FILE", str(logs_dir / "installer.log"))

        from core.process import cmd_status
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

        # core.process binds this name at import time, so patch it there
        monkeypatch.setattr("core.process.SERVICES_STATE_PATH", state_path)
        monkeypatch.setattr("core.config.LOG_FILE", str(logs_dir / "installer.log"))

        from core.process import load_services_state, save_services_state

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

        monkeypatch.setattr("core.config.ROOT_DIR", str(tmp_path))
        monkeypatch.setattr("core.config.CORE_DIR", str(tmp_path / "core"))
        monkeypatch.setattr("core.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("core.config.GENERATED_DIR", str(generated_dir))
        monkeypatch.setattr("core.config.LOGS_DIR", str(logs_dir))
        monkeypatch.setattr("core.config.SETTINGS_PATH", str(config_dir / "settings.yaml"))
        monkeypatch.setattr("core.config.PROVIDERS_PATH", str(config_dir / "providers.yaml"))
        monkeypatch.setattr("core.config.MODELS_PATH", str(config_dir / "models.yaml"))
        monkeypatch.setattr("core.config.LITELLM_CONFIG_PATH", str(generated_dir / "config.yaml"))
        monkeypatch.setattr("core.config.OPENCLAW_CONFIG_PATH", str(generated_dir / "openclaw.json"))
        monkeypatch.setattr("core.config.LOG_FILE", str(logs_dir / "installer.log"))

        # Mock discovery to avoid PowerShell calls
        mock_discovery = MagicMock()
        mock_discovery.run_all_discovery.return_value = {
            "specs": {"os": "Windows", "cpu": "Test", "ram_gb": 16, "gpus": [], "disk": {}},
            "tools": {"python": "python.exe"},
            "recommendations": {"tier": "medium", "recommendation": "Test"},
            "ollama": {"online": False, "models": []},
        }
        mock_discovery.get_ollama_models.return_value = []
        monkeypatch.setitem(sys.modules, "core.discovery", mock_discovery)
        # `from . import discovery` resolves via the package attribute when the
        # real module was already imported, so patch that too.
        monkeypatch.setattr("core.discovery", mock_discovery, raising=False)

        # Patch subprocess and shutil for version validation in cmd_configure
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(stdout="1.0.0", returncode=0)
        monkeypatch.setattr("core.config.subprocess.run", mock_run)
        monkeypatch.setattr("core.config.shutil.which", MagicMock(return_value="/mocked/path"))

        from core.config import cmd_configure
        cmd_configure()

        litellm_config_path = str(generated_dir / "config.yaml")
        assert os.path.exists(litellm_config_path)

    def test_configure_rotates_insecure_gateway_token(self, tmp_path, monkeypatch):
        """Any gateway token that is not a 48-char hex secret must be rotated on upgrade."""
        import json
        import re

        config_dir = tmp_path / "OpenClawManager"
        config_dir.mkdir()
        claw_home = tmp_path / ".openclaw"
        claw_home.mkdir()
        (claw_home / "openclaw.json").write_text(json.dumps({
            "gateway": {"auth": {"mode": "token", "token": "legacy-default-token"}},
        }))

        (config_dir / "settings.yaml").write_text(
            "litellm:\n  port: 4000\n  api_key: sk-test-key\n"
            f"openclaw:\n  port: 18789\n  config_dir: '{claw_home.as_posix()}'\n"
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

        monkeypatch.setattr("core.config.ROOT_DIR", str(tmp_path))
        monkeypatch.setattr("core.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("core.config.GENERATED_DIR", str(generated_dir))
        monkeypatch.setattr("core.config.LOGS_DIR", str(logs_dir))
        monkeypatch.setattr("core.config.SETTINGS_PATH", str(config_dir / "settings.yaml"))
        monkeypatch.setattr("core.config.PROVIDERS_PATH", str(config_dir / "providers.yaml"))
        monkeypatch.setattr("core.config.MODELS_PATH", str(config_dir / "models.yaml"))
        monkeypatch.setattr("core.config.LITELLM_CONFIG_PATH", str(generated_dir / "config.yaml"))
        monkeypatch.setattr("core.config.OPENCLAW_CONFIG_PATH", str(generated_dir / "openclaw.json"))
        monkeypatch.setattr("core.config.LOG_FILE", str(logs_dir / "installer.log"))

        mock_discovery = MagicMock()
        mock_discovery.run_all_discovery.return_value = {
            "specs": {"os": "Windows", "cpu": "Test", "ram_gb": 16, "gpus": [], "disk": {}},
            "tools": {"python": "python.exe"},
            "recommendations": {"tier": "medium", "recommendation": "Test"},
            "ollama": {"online": False, "models": []},
        }
        mock_discovery.get_ollama_models.return_value = []
        monkeypatch.setitem(sys.modules, "core.discovery", mock_discovery)
        monkeypatch.setattr("core.discovery", mock_discovery, raising=False)

        # Patch subprocess and shutil for version validation in cmd_configure
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(stdout="1.0.0", returncode=0)
        monkeypatch.setattr("core.config.subprocess.run", mock_run)
        monkeypatch.setattr("core.config.shutil.which", MagicMock(return_value="/mocked/path"))

        from core.config import cmd_configure
        cmd_configure()

        rotated = json.loads((claw_home / "openclaw.json").read_text())
        new_token = rotated["gateway"]["auth"]["token"]
        assert new_token != "legacy-default-token"
        assert re.fullmatch(r"[0-9a-f]{48}", new_token)
