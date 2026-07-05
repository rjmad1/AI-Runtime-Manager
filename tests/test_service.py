# tests/test_service.py
# Unit tests for core/service.py — OS service integration.

import platform

from core import service
from core.process import watch_loop


class TestSystemdUnit:
    """The generated unit must encode restart policy and the watchdog entry point."""

    def test_unit_contents(self):
        unit = service.systemd_unit()
        assert "Restart=on-failure" in unit
        assert "RestartSec=5" in unit
        assert "-m core.manager watch" in unit
        assert "WantedBy=default.target" in unit
        assert f"WorkingDirectory={service.ROOT_DIR}" in unit


class TestCmdService:
    def test_unknown_action_is_rejected(self, monkeypatch):
        calls = []
        monkeypatch.setattr(service, "_windows", lambda a: calls.append(a))
        monkeypatch.setattr(service, "_linux", lambda a: calls.append(a))
        service.cmd_service("explode")
        assert calls == []

    def test_dispatches_to_platform(self, monkeypatch):
        calls = []
        monkeypatch.setattr(service, "_windows", lambda a: calls.append(("win", a)))
        monkeypatch.setattr(service, "_linux", lambda a: calls.append(("linux", a)))
        service.cmd_service("status")
        expected = {"Windows": ("win", "status"), "Linux": ("linux", "status")}.get(platform.system())
        if expected:
            assert calls == [expected]
        else:
            assert calls == []  # macOS and others: unsupported, no dispatch

    def test_windows_status_handles_missing_service(self, monkeypatch):
        if platform.system() != "Windows":
            return
        # QueryServiceStatus raising (error 1060: not installed) must not crash
        if service.HAS_PYWIN32:
            def boom(name):
                raise OSError("service does not exist")
            monkeypatch.setattr(service.win32serviceutil, "QueryServiceStatus", boom)
        service.cmd_service("status")


class TestWatchLoop:
    """The extracted watchdog loop honors injected stop/wait hooks."""

    def test_stops_when_should_stop(self, monkeypatch):
        monkeypatch.setattr("core.process.check_and_heal", lambda: True)
        ticks = []

        def wait(delay):
            ticks.append(delay)

        watch_loop(poll_seconds=7, wait=wait, should_stop=lambda: len(ticks) >= 3)
        assert ticks == [7, 7, 7]  # healthy stack: plain poll interval, then stop

    def test_backoff_on_persistent_failure(self, monkeypatch):
        monkeypatch.setattr("core.process.check_and_heal", lambda: False)
        ticks = []
        watch_loop(poll_seconds=10, wait=ticks.append, should_stop=lambda: len(ticks) >= 6)
        assert ticks == [20, 40]  # halts after 3 consecutive failures
