# tests/test_repair.py
# Unit tests for core/repair.py — inventory-driven dependency remediation.

import json

import pytest

from core import repair


def _fake_inventory(missing, present=()):
    items = [{"name": n, "category": "x", "status": "missing", "version": "", "path": "", "details": ""}
             for n in missing]
    items += [{"name": n, "category": "x", "status": "present", "version": "1.0", "path": "/bin/" + n, "details": ""}
              for n in present]
    return {"schema_version": 1, "items": items}


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """Isolate repair from the real system: fake inventory, fake winget, tmp report dir."""
    monkeypatch.setattr(repair, "GENERATED_DIR", str(tmp_path))
    monkeypatch.setattr(repair, "_pkg_manager", lambda: ("winget", "C:\\winget.exe"))
    return tmp_path


class TestStrategies:
    """Every inventory item name must have a remediation strategy."""

    def test_all_strategies_have_a_remediation_path(self):
        for name, strat in repair.STRATEGIES.items():
            assert ("winget" in strat and "brew" in strat) or "manual" in strat or "bundled_with" in strat, name


class TestRepairDependencies:
    def test_all_present_returns_empty(self, patched, monkeypatch):
        monkeypatch.setattr("core.discovery.discover_dependency_inventory",
                            lambda specs=None: _fake_inventory([], present=["git"]))
        assert repair.repair_dependencies(interactive=False) == []

    def test_non_interactive_plans_without_installing(self, patched, monkeypatch):
        monkeypatch.setattr("core.discovery.discover_dependency_inventory",
                            lambda specs=None: _fake_inventory(["ollama", "cuda"]))
        monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("input() must not be called"))
        monkeypatch.setattr(repair, "install_dependency",
                            lambda *a: pytest.fail("install must not be called"))

        results = {r["name"]: r["status"] for r in repair.repair_dependencies(interactive=False)}
        assert results == {"ollama": "pending_consent", "cuda": "manual"}

    def test_interactive_consent_installs(self, patched, monkeypatch):
        monkeypatch.setattr("core.discovery.discover_dependency_inventory",
                            lambda specs=None: _fake_inventory(["ollama"]))
        monkeypatch.setattr("builtins.input", lambda *_: "yes")
        monkeypatch.setattr(repair, "install_dependency",
                            lambda name, m, e: {"name": name, "status": "repaired"})

        results = repair.repair_dependencies(interactive=True)
        assert results == [{"name": "ollama", "status": "repaired"}]

    def test_interactive_decline_skips(self, patched, monkeypatch):
        monkeypatch.setattr("core.discovery.discover_dependency_inventory",
                            lambda specs=None: _fake_inventory(["ollama"]))
        monkeypatch.setattr("builtins.input", lambda *_: "no")

        results = repair.repair_dependencies(interactive=True)
        assert results[0]["status"] == "skipped"

    def test_npm_deduped_when_node_missing(self, patched, monkeypatch):
        monkeypatch.setattr("core.discovery.discover_dependency_inventory",
                            lambda specs=None: _fake_inventory(["node", "npm"]))
        monkeypatch.setattr("builtins.input", lambda *_: "yes")
        monkeypatch.setattr(repair, "install_dependency",
                            lambda name, m, e: {"name": name, "status": "repaired"})

        results = {r["name"]: r["status"] for r in repair.repair_dependencies(interactive=True)}
        assert results["node"] == "repaired"
        assert results["npm"] == "manual"  # bundled_with guidance, no second install

    def test_no_package_manager_means_manual_guidance(self, patched, monkeypatch):
        monkeypatch.setattr(repair, "_pkg_manager", lambda: (None, None))
        monkeypatch.setattr("core.discovery.discover_dependency_inventory",
                            lambda specs=None: _fake_inventory(["git"]))

        results = repair.repair_dependencies(interactive=True)
        assert results[0]["status"] == "manual"

    def test_writes_audit_report(self, patched, monkeypatch):
        monkeypatch.setattr("core.discovery.discover_dependency_inventory",
                            lambda specs=None: _fake_inventory(["cuda"]))
        repair.repair_dependencies(interactive=False)

        with open(patched / "repair-report.json", encoding="utf-8") as f:
            report = json.load(f)
        assert report["schema_version"] == 1
        assert report["results"][0]["name"] == "cuda"


class TestInstallDependency:
    class _Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def test_failed_install_reports_failed(self, monkeypatch):
        monkeypatch.setattr(repair.subprocess, "run", lambda *a, **k: self._Result(1, stderr="boom"))
        result = repair.install_dependency("git", "winget", "winget")
        assert result["status"] == "failed"
        assert "boom" in result["details"]

    def test_success_with_validation_reports_repaired(self, monkeypatch):
        monkeypatch.setattr(repair.subprocess, "run", lambda *a, **k: self._Result(0))
        monkeypatch.setattr(repair, "_validate_installed",
                            lambda name: {"path": "/bin/git", "version": "2.50.0"})
        result = repair.install_dependency("git", "winget", "winget")
        assert result["status"] == "repaired"
        assert result["version"] == "2.50.0"

    def test_success_without_validation_reports_unverified(self, monkeypatch):
        monkeypatch.setattr(repair.subprocess, "run", lambda *a, **k: self._Result(0))
        monkeypatch.setattr(repair, "_validate_installed", lambda name: {})
        result = repair.install_dependency("git", "winget", "winget")
        assert result["status"] == "installed_unverified"
