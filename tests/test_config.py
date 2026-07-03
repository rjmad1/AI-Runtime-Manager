# tests/test_config.py
# Unit tests for core/config.py — YAML I/O, logging, env var helpers.

import importlib
import os

import core.config
from core.config import load_yaml, log, save_yaml, set_windows_env


class TestLoadYaml:
    """Tests for load_yaml."""

    def test_load_valid_yaml(self, tmp_path):
        """load_yaml should parse a valid YAML file into a dict."""
        path = tmp_path / "test.yaml"
        path.write_text("key: value\nnested:\n  a: 1\n  b: 2\n", encoding="utf-8")
        result = load_yaml(str(path))
        assert result == {"key": "value", "nested": {"a": 1, "b": 2}}

    def test_load_nonexistent_file(self):
        """load_yaml should return empty dict for missing files."""
        result = load_yaml("/nonexistent/path/file.yaml")
        assert result == {}

    def test_load_empty_file(self, tmp_path):
        """load_yaml should return empty dict for empty YAML."""
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        result = load_yaml(str(path))
        assert result == {}

    def test_load_corrupted_yaml(self, tmp_path):
        """load_yaml should return empty dict for malformed YAML."""
        path = tmp_path / "bad.yaml"
        path.write_text("{{{{invalid yaml: [}", encoding="utf-8")
        result = load_yaml(str(path))
        assert result == {}


class TestSaveYaml:
    """Tests for save_yaml."""

    def test_save_and_reload(self, tmp_path):
        """save_yaml output should be loadable by load_yaml."""
        data = {"litellm": {"port": 4000, "api_key": "test-key"}, "flag": True}
        path = str(tmp_path / "out.yaml")
        save_yaml(data, path)
        reloaded = load_yaml(path)
        assert reloaded == data

    def test_save_creates_file(self, tmp_path):
        """save_yaml should create the file if it doesn't exist."""
        path = str(tmp_path / "new.yaml")
        assert not os.path.exists(path)
        save_yaml({"a": 1}, path)
        assert os.path.exists(path)


class TestLog:
    """Tests for the log function."""

    def test_log_writes_to_file(self, tmp_path, monkeypatch):
        """log should append messages to the log file."""
        log_path = str(tmp_path / "test.log")
        monkeypatch.setattr("core.config.LOG_FILE", log_path)
        log("INFO", "Test message")
        assert os.path.exists(log_path)
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Test message" in content
        assert "[INFO]" in content

    def test_log_masks_api_keys(self, tmp_path, monkeypatch):
        """log should mask API keys in output."""
        log_path = str(tmp_path / "mask.log")
        monkeypatch.setattr("core.config.LOG_FILE", log_path)
        log("INFO", "Key is sk-abcdefghijkl1234567890")
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "sk-abcdefghijkl..." in content
        assert "1234567890" not in content


class TestSetWindowsEnv:
    """Tests for set_windows_env injection safety."""

    def test_escapes_single_quotes(self, monkeypatch):
        """set_windows_env should escape single quotes to prevent PS injection."""
        captured_cmds = []

        def mock_run(args, **kwargs):
            captured_cmds.append(args)
            class FakeResult:
                returncode = 0
            return FakeResult()

        monkeypatch.setattr("core.config.subprocess.run", mock_run)
        set_windows_env("TEST_KEY", "value'with;injection")

        assert len(captured_cmds) == 1
        cmd_str = captured_cmds[0][-1]
        assert "''" in cmd_str  # Single quotes should be doubled
        assert "value'with" not in cmd_str  # Raw single quote should not appear

    def test_sets_os_environ_on_success(self, monkeypatch):
        """set_windows_env should update os.environ on success."""
        def mock_run(args, **kwargs):
            class FakeResult:
                returncode = 0
            return FakeResult()

        monkeypatch.setattr("core.config.subprocess.run", mock_run)
        set_windows_env("TEST_ENV_VAR", "test_value")
        assert os.environ.get("TEST_ENV_VAR") == "test_value"
        # Cleanup
        if "TEST_ENV_VAR" in os.environ:
            del os.environ["TEST_ENV_VAR"]


class TestRuntimeDirs:
    """Directory creation must be explicit, never an import side effect."""

    def test_import_does_not_create_directories(self, monkeypatch):
        """Re-executing the module body must not call os.makedirs."""
        calls = []
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: calls.append(a))
        importlib.reload(core.config)
        assert calls == []

    def test_ensure_runtime_dirs_creates_directories(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setattr("core.config.GENERATED_DIR", str(tmp_path / "gen"))
        monkeypatch.setattr("core.config.LOGS_DIR", str(tmp_path / "logs"))
        core.config.ensure_runtime_dirs()
        assert (tmp_path / "cfg").is_dir()
        assert (tmp_path / "gen").is_dir()
        assert (tmp_path / "logs").is_dir()
