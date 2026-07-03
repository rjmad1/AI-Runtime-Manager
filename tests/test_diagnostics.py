# tests/test_diagnostics.py
# Regression tests for core/diagnostics.py error handling.

import sys
from unittest.mock import MagicMock

import pytest

from core.diagnostics import LiteLLMOfflineError, cmd_diagnose


def test_cmd_diagnose_raises_when_litellm_offline(tmp_path, monkeypatch):
    """cmd_diagnose must raise LiteLLMOfflineError (not sys.exit) when the proxy is down."""
    monkeypatch.setattr("core.config.LOG_FILE", str(tmp_path / "installer.log"))
    monkeypatch.setattr("core.diagnostics.load_yaml", lambda path: {"litellm": {"port": 4000}})
    monkeypatch.setattr("core.diagnostics.get_pids_on_port", lambda port: [])

    mock_discovery = MagicMock()
    mock_discovery.run_all_discovery.return_value = {
        "specs": {"os": "Windows", "gpus": []},
        "tools": {},
    }
    monkeypatch.setitem(sys.modules, "core.discovery", mock_discovery)
    monkeypatch.setattr("core.discovery", mock_discovery, raising=False)

    with pytest.raises(LiteLLMOfflineError):
        cmd_diagnose()
