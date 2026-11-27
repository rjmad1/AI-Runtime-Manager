# tests/test_litellm_key_env.py
# Consumer-level tests (dummy values only) for env-referenced litellm.api_key:
# cmd_configure (no write-back, fail closed, generate path unchanged), cmd_start (env resolution).
import sys
from unittest.mock import MagicMock

import pytest

from core.secret_ref import MissingSecretError

DUMMY = "dummy-not-a-secret-123"
SETTINGS_TMPL = (
    "litellm:\n  port: 4000\n  api_key: {key}\n  drop_params: true\n"
    "  set_verbose: false\n  routing_strategy: latency-based-routing\n"
    "  num_retries: 3\n  request_timeout: 30\n"
    "openclaw:\n  port: 18789\n  config_dir: ''\n"
    "ollama:\n  enabled: false\n"
)


def _setup(tmp_path, monkeypatch, key_yaml):
    cfg = tmp_path / "OpenClawManager"
    cfg.mkdir()
    gen = tmp_path / "generated"
    gen.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    (cfg / "settings.yaml").write_text(SETTINGS_TMPL.format(key=key_yaml))
    (cfg / "providers.yaml").write_text("gemini:\n  enabled: false\n  env_var: GEMINI_API_KEY\n  info: Test\n")
    (cfg / "models.yaml").write_text(
        "models:\n  - id: test-model\n    name: Test Model\n    provider: gemini\n"
        "    litellm_model: gemini/test\n    context_window: 4096\n    max_tokens: 4096\n"
    )
    for name, val in {
        "ROOT_DIR": str(tmp_path), "CORE_DIR": str(tmp_path / "core"), "CONFIG_DIR": str(cfg),
        "GENERATED_DIR": str(gen), "LOGS_DIR": str(logs),
        "SETTINGS_PATH": str(cfg / "settings.yaml"), "PROVIDERS_PATH": str(cfg / "providers.yaml"),
        "MODELS_PATH": str(cfg / "models.yaml"), "LITELLM_CONFIG_PATH": str(gen / "config.yaml"),
        "OPENCLAW_CONFIG_PATH": str(gen / "openclaw.json"), "LOG_FILE": str(logs / "installer.log"),
    }.items():
        monkeypatch.setattr(f"core.config.{name}", val)
    disc = MagicMock()
    disc.run_all_discovery.return_value = {
        "specs": {"os": "Windows", "cpu": "Test", "ram_gb": 16, "gpus": [], "disk": {}},
        "tools": {"python": "python.exe"},
        "recommendations": {"tier": "medium", "recommendation": "Test"},
        "ollama": {"online": False, "models": []},
    }
    disc.get_ollama_models.return_value = []
    monkeypatch.setitem(sys.modules, "core.discovery", disc)
    monkeypatch.setattr("core.discovery", disc, raising=False)
    run = MagicMock()
    run.return_value = MagicMock(stdout="1.0.0", returncode=0)
    monkeypatch.setattr("core.config.subprocess.run", run)
    monkeypatch.setattr("core.config.shutil.which", MagicMock(return_value="/mocked/path"))
    # keep the sync of the gateway config inside tmp (do not touch a real home dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return cfg, gen, logs


def _all_text(*dirs):
    out = ""
    for d in dirs:
        for p in d.rglob("*"):
            if p.is_file():
                out += p.read_text(errors="replace")
    return out


def test_configure_with_reference_does_not_write_or_leak(tmp_path, monkeypatch, capsys):
    cfg, gen, logs = _setup(tmp_path, monkeypatch, "os.environ/AIRM_TEST_KEY")
    monkeypatch.setenv("AIRM_TEST_KEY", DUMMY)
    before = (cfg / "settings.yaml").read_bytes()
    from core.config import cmd_configure
    cmd_configure()
    assert (cfg / "settings.yaml").read_bytes() == before  # no write-back, no generated literal
    out = capsys.readouterr()
    assert DUMMY not in _all_text(tmp_path) and DUMMY not in out.out + out.err


def test_configure_with_missing_reference_fails_closed(tmp_path, monkeypatch):
    cfg, gen, logs = _setup(tmp_path, monkeypatch, "os.environ/AIRM_TEST_KEY")
    monkeypatch.delenv("AIRM_TEST_KEY", raising=False)
    before = (cfg / "settings.yaml").read_bytes()
    from core.config import cmd_configure
    with pytest.raises(MissingSecretError):
        cmd_configure()
    assert (cfg / "settings.yaml").read_bytes() == before
    assert not (gen / "config.yaml").exists()


def test_configure_empty_key_still_generates(tmp_path, monkeypatch):
    cfg, gen, logs = _setup(tmp_path, monkeypatch, '""')
    from core.config import cmd_configure, load_yaml
    cmd_configure()
    key = load_yaml(str(cfg / "settings.yaml"))["litellm"]["api_key"]
    assert key.startswith("sk-airm-") and len(key) > 20


def test_start_resolves_reference_into_child_env_only(tmp_path, monkeypatch):
    cfg, gen, logs = _setup(tmp_path, monkeypatch, "os.environ/AIRM_TEST_KEY")
    monkeypatch.setenv("AIRM_TEST_KEY", DUMMY)
    monkeypatch.setenv("LITELLM_API_KEY", "placeholder")  # ensures restore after the test
    monkeypatch.delenv("LITELLM_API_KEY")
    from core import process
    monkeypatch.setattr(process, "_check_port_conflicts", lambda *a, **k: None)
    monkeypatch.setattr(process, "_run_vram_profiling", lambda *a, **k: None)
    monkeypatch.setattr(process, "cmd_configure", lambda: None)
    monkeypatch.setattr(process, "_spawn_litellm", lambda port: MagicMock(pid=1))
    monkeypatch.setattr(process, "_spawn_openclaw", lambda *a, **k: MagicMock(pid=2))
    monkeypatch.setattr(process, "save_services_state", lambda s: None)
    monkeypatch.setattr(process, "SETTINGS_PATH", str(cfg / "settings.yaml"))
    monkeypatch.setattr(process, "PROVIDERS_PATH", str(cfg / "providers.yaml"))
    before = (cfg / "settings.yaml").read_bytes()
    process.cmd_start()
    import os
    assert os.environ["LITELLM_API_KEY"] == DUMMY
    assert (cfg / "settings.yaml").read_bytes() == before


def test_start_missing_reference_fails_closed(tmp_path, monkeypatch):
    cfg, gen, logs = _setup(tmp_path, monkeypatch, "os.environ/AIRM_TEST_KEY")
    monkeypatch.delenv("AIRM_TEST_KEY", raising=False)
    from core import process
    monkeypatch.setattr(process, "SETTINGS_PATH", str(cfg / "settings.yaml"))
    spawned = []
    monkeypatch.setattr(process, "_spawn_litellm", lambda port: spawned.append(1))
    with pytest.raises(MissingSecretError):
        process.cmd_start()
    assert not spawned


def test_diagnose_missing_reference_fails_closed_before_network(tmp_path, monkeypatch):
    cfg, gen, logs = _setup(tmp_path, monkeypatch, "os.environ/AIRM_TEST_KEY")
    monkeypatch.delenv("AIRM_TEST_KEY", raising=False)
    from core import diagnostics
    monkeypatch.setattr(diagnostics, "SETTINGS_PATH", str(cfg / "settings.yaml"))
    monkeypatch.setattr(diagnostics, "PROVIDERS_PATH", str(cfg / "providers.yaml"))
    monkeypatch.setattr(diagnostics, "MODELS_PATH", str(cfg / "models.yaml"))
    bench = MagicMock()
    monkeypatch.setattr(diagnostics, "_run_benchmarks", bench)
    with pytest.raises(MissingSecretError):
        diagnostics.cmd_diagnose()
    bench.assert_not_called()
