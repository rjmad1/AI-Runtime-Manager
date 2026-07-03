# tests/test_process.py
# Regression tests for the self-healing watchdog and health probing.

from core import process


def test_check_and_heal_healthy_stack_does_not_restart(monkeypatch):
    """No restart when both daemons are alive."""
    calls = []
    monkeypatch.setattr(process, "_stack_health", lambda: {"litellm": True, "openclaw": True})
    monkeypatch.setattr(process, "cmd_stop", lambda: calls.append("stop"))
    monkeypatch.setattr(process, "cmd_start", lambda: calls.append("start"))

    assert process.check_and_heal() is True
    assert calls == []


def test_check_and_heal_restarts_dead_stack(tmp_path, monkeypatch):
    """A dead daemon triggers stop+start and reports recovery."""
    monkeypatch.setattr("core.config.LOG_FILE", str(tmp_path / "installer.log"))
    calls = []
    health = iter([
        {"litellm": False, "openclaw": True},   # initial check: litellm down
        {"litellm": True, "openclaw": True},    # post-restart check: recovered
    ])
    monkeypatch.setattr(process, "_stack_health", lambda: next(health))
    monkeypatch.setattr(process, "cmd_stop", lambda: calls.append("stop"))
    monkeypatch.setattr(process, "cmd_start", lambda: calls.append("start"))

    assert process.check_and_heal() is True
    assert calls == ["stop", "start"]


def test_check_and_heal_reports_failed_restart(tmp_path, monkeypatch):
    """A restart that raises must return False, not propagate."""
    monkeypatch.setattr("core.config.LOG_FILE", str(tmp_path / "installer.log"))
    monkeypatch.setattr(process, "_stack_health", lambda: {"litellm": False, "openclaw": False})
    monkeypatch.setattr(process, "cmd_stop", lambda: None)

    def boom():
        raise RuntimeError("spawn failed")
    monkeypatch.setattr(process, "cmd_start", boom)

    assert process.check_and_heal() is False


def test_litellm_ready_false_when_offline():
    """Readiness probe returns False when nothing is listening."""
    assert process.litellm_ready(1, timeout=0.2) is False
