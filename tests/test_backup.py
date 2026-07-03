# tests/test_backup.py
# Unit tests for core/backup.py — backup creation and restore with Zip Slip prevention.

import os
import zipfile


class TestBackupCreate:
    """Tests for backup archive creation."""

    def test_backup_creates_zip(self, tmp_path, monkeypatch):
        """cmd_backup should create a valid ZIP archive."""
        # Setup temp config structure
        config_dir = tmp_path / "OpenClawManager"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text("litellm:\n  port: 4000\n")
        (config_dir / "providers.yaml").write_text("gemini:\n  enabled: true\n")
        (config_dir / "models.yaml").write_text("models: []\n")

        generated_dir = tmp_path / "generated"
        generated_dir.mkdir()
        (generated_dir / "config.yaml").write_text("model_list: []\n")

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        # Monkey-patch constants
        monkeypatch.setattr("core.config.ROOT_DIR", str(tmp_path))
        monkeypatch.setattr("core.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("core.config.GENERATED_DIR", str(generated_dir))
        monkeypatch.setattr("core.config.LOGS_DIR", str(logs_dir))
        monkeypatch.setattr("core.config.SETTINGS_PATH", str(config_dir / "settings.yaml"))
        monkeypatch.setattr("core.config.LOG_FILE", str(logs_dir / "installer.log"))

        from core.backup import cmd_backup
        zip_path = cmd_backup()

        assert zip_path is not None
        assert os.path.exists(zip_path)
        assert zip_path.endswith(".zip")

        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            assert any("settings.yaml" in n for n in names)
            assert any("providers.yaml" in n for n in names)


class TestZipSlipPrevention:
    """Tests for Zip Slip path traversal prevention in restore."""

    def test_malicious_zip_rejected(self, tmp_path, monkeypatch):
        """Restore should reject archives with path traversal entries."""
        # Create a malicious ZIP with path traversal
        evil_zip = tmp_path / "evil.zip"
        with zipfile.ZipFile(str(evil_zip), "w") as z:
            z.writestr("../../etc/passwd", "root:x:0:0:root")

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        import shutil
        shutil.copy(str(evil_zip), str(backup_dir / "evil_backup.zip"))

        config_dir = tmp_path / "OpenClawManager"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text(
            "lifecycle:\n  backup_dir: backups\n"
        )

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        monkeypatch.setattr("core.config.ROOT_DIR", str(tmp_path))
        monkeypatch.setattr("core.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("core.config.SETTINGS_PATH", str(config_dir / "settings.yaml"))
        monkeypatch.setattr("core.config.LOG_FILE", str(logs_dir / "installer.log"))

        # Mock cmd_configure to avoid side effects
        monkeypatch.setattr("core.config.cmd_configure", lambda: None)

        from core.backup import cmd_restore
        result = cmd_restore(backup_idx=0)
        assert not result  # Should fail due to Zip Slip detection
