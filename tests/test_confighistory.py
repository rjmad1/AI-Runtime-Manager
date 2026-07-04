# tests/test_confighistory.py
# Unit tests for core/confighistory.py — configuration versioning.

import os

import pytest

from core import confighistory
from core.config import save_yaml


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Versioned config dir + history dir under tmp; audit muted."""
    cfg_dir = tmp_path / "cfg"
    hist_dir = cfg_dir / "history"
    cfg_dir.mkdir()
    monkeypatch.setattr(confighistory, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(confighistory, "HISTORY_DIR", str(hist_dir))
    monkeypatch.setattr(confighistory, "INDEX_PATH", str(hist_dir / "index.json"))
    monkeypatch.setattr(confighistory, "_audit", lambda *a, **k: None)
    return cfg_dir


def _settings(cfg_dir):
    return os.path.join(str(cfg_dir), "settings.yaml")


class TestSnapshotting:
    def test_first_save_has_no_snapshot_then_history_grows(self, isolated):
        path = _settings(isolated)
        save_yaml({"litellm": {"port": 4000}}, path)          # nothing to snapshot yet
        assert confighistory.history_list() == []
        save_yaml({"litellm": {"port": 4001}}, path)          # snapshots the 4000 version
        entries = confighistory.history_list("settings.yaml")
        assert len(entries) == 1 and entries[0]["id"] == 1

    def test_identical_content_not_duplicated(self, isolated):
        path = _settings(isolated)
        save_yaml({"a": 1}, path)
        save_yaml({"a": 2}, path)
        save_yaml({"a": 2}, path)  # same bytes as on disk → no new snapshot
        assert len(confighistory.history_list()) == 1

    def test_non_versioned_files_ignored(self, isolated):
        save_yaml({"users": {}}, os.path.join(str(isolated), "users.yaml"))
        save_yaml({"users": {}}, os.path.join(str(isolated), "users.yaml"))
        assert confighistory.history_list() == []


class TestConflictDetection:
    def test_out_of_band_edit_flagged(self, isolated):
        path = _settings(isolated)
        save_yaml({"a": 1}, path)
        # Simulate a manual edit outside AIRM
        with open(path, "a", encoding="utf-8") as f:
            f.write("# hand-edited\n")
        save_yaml({"a": 2}, path)
        entries = confighistory.history_list()
        assert entries[-1]["conflict"] is True

    def test_managed_writes_not_flagged(self, isolated):
        path = _settings(isolated)
        save_yaml({"a": 1}, path)
        save_yaml({"a": 2}, path)
        assert all(not e["conflict"] for e in confighistory.history_list())


class TestDiffRollbackTag:
    def test_diff_shows_change(self, isolated):
        path = _settings(isolated)
        save_yaml({"port": 4000}, path)
        save_yaml({"port": 5000}, path)
        text = confighistory.diff(1)
        assert "-port: 4000" in text and "+port: 5000" in text

    def test_rollback_restores_and_is_reversible(self, isolated):
        path = _settings(isolated)
        save_yaml({"port": 4000}, path)
        save_yaml({"port": 5000}, path)
        assert confighistory.rollback(1)
        assert "4000" in open(path, encoding="utf-8").read()
        # The 5000 version was snapshotted by the rollback itself
        shas = [e["sha256"] for e in confighistory.history_list()]
        assert len(shas) == 2 and len(set(shas)) == 2

    def test_rollback_unknown_id_fails(self, isolated):
        assert confighistory.rollback(999) is False

    def test_tag(self, isolated):
        path = _settings(isolated)
        save_yaml({"a": 1}, path)
        save_yaml({"a": 2}, path)
        assert confighistory.tag(1, "known-good")
        assert confighistory.history_list()[0]["tag"] == "known-good"


class TestPruning:
    def test_old_snapshots_pruned(self, isolated, monkeypatch):
        monkeypatch.setattr(confighistory, "MAX_SNAPSHOTS_PER_FILE", 3)
        path = _settings(isolated)
        for i in range(6):
            save_yaml({"v": i}, path)
        entries = confighistory.history_list("settings.yaml")
        assert len(entries) == 3
        # Snapshot files for pruned entries are gone from disk
        on_disk = [f for f in os.listdir(confighistory.HISTORY_DIR) if f.endswith(".yaml")]
        assert len(on_disk) == 3
