# tests/test_migrations.py
# Unit tests for core/migrations.py — version migration framework.

import pytest

from core import migrations


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Isolated schema state, synthetic migration table, no real backups."""
    monkeypatch.setattr(migrations, "SCHEMA_STATE_PATH", str(tmp_path / "schema-version.json"))
    applied = []

    def make(version, reversible=True, fail=False):
        def up():
            if fail:
                raise RuntimeError("boom")
            applied.append(("up", version))
        def down():
            applied.append(("down", version))
        return {"version": version, "description": f"step {version}",
                "upgrade": up, "downgrade": down if reversible else None}

    table = [make(1), make(2, reversible=False), make(3)]
    monkeypatch.setattr(migrations, "MIGRATIONS", table)
    return {"applied": applied, "table": table, "make": make, "tmp": tmp_path}


def _no_backup():
    return None


class TestMigrate:
    def test_applies_all_pending_in_order(self, isolated):
        assert migrations.migrate(make_backup=_no_backup) == 3
        assert isolated["applied"] == [("up", 1), ("up", 2), ("up", 3)]
        assert migrations.current_version() == 3

    def test_idempotent_when_current(self, isolated):
        migrations.migrate(make_backup=_no_backup)
        assert migrations.migrate(make_backup=_no_backup) == 0

    def test_history_recorded(self, isolated):
        migrations.migrate(make_backup=_no_backup)
        history = migrations.status()["history"]
        assert [h["version"] for h in history] == [1, 2, 3]
        assert all(h["direction"] == "upgrade" for h in history)

    def test_failure_stops_and_preserves_progress(self, isolated, monkeypatch):
        table = [isolated["make"](1), isolated["make"](2, fail=True), isolated["make"](3)]
        monkeypatch.setattr(migrations, "MIGRATIONS", table)
        with pytest.raises(migrations.MigrationError):
            migrations.migrate(make_backup=_no_backup)
        # v1 persisted before the failure; v3 never ran
        assert migrations.current_version() == 1
        assert ("up", 3) not in isolated["applied"]

    def test_failure_restores_backup(self, isolated, monkeypatch):
        table = [isolated["make"](1, fail=True)]
        monkeypatch.setattr(migrations, "MIGRATIONS", table)
        restored = []
        monkeypatch.setattr(migrations, "_restore_backup", lambda z: restored.append(z))
        with pytest.raises(migrations.MigrationError):
            migrations.migrate(make_backup=lambda: "backup.zip")
        assert restored == ["backup.zip"]


class TestRollback:
    def test_reversible_range_rolls_back(self, isolated):
        migrations.migrate(make_backup=_no_backup)
        assert migrations.rollback(2) == 1  # v3 → v2 (v3 is reversible)
        assert migrations.current_version() == 2
        assert isolated["applied"][-1] == ("down", 3)

    def test_irreversible_range_refused(self, isolated):
        migrations.migrate(make_backup=_no_backup)
        with pytest.raises(migrations.MigrationError, match="no downgrade path"):
            migrations.rollback(1)  # crosses irreversible v2
        assert migrations.current_version() == 3  # untouched

    def test_noop_when_at_or_below_target(self, isolated):
        migrations.migrate(make_backup=_no_backup)
        assert migrations.rollback(3) == 0


class TestEnsureCurrent:
    def test_auto_migrates(self, isolated, monkeypatch):
        monkeypatch.setattr(migrations, "migrate", lambda: 3)
        migrations.ensure_current()  # no raise

    def test_newer_schema_refused(self, isolated):
        migrations._save_state({"version": 99, "history": []})
        with pytest.raises(migrations.MigrationError, match="newer than this AIRM build"):
            migrations.ensure_current()


class TestStatus:
    def test_pending_reported_with_reversibility(self, isolated):
        info = migrations.status()
        assert info["current_version"] == 0
        assert [p["version"] for p in info["pending"]] == [1, 2, 3]
        assert [p["reversible"] for p in info["pending"]] == [True, False, True]
