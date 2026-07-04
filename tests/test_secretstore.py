# tests/test_secretstore.py
# Unit tests for core/secretstore.py — secure credential management.

import json
import os
import platform

import pytest

from core import secretstore
from core.config import get_windows_env, set_windows_env

_TEST_NAME = "AIRM_TEST_SECRET_XYZ"


@pytest.fixture(autouse=True)
def audit_to_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(secretstore, "AUDIT_LOG", str(tmp_path / "audit.log"))
    yield tmp_path


class TestOsBackendRoundtrip:
    """Real credential-store write/read/rotate/delete on the host OS."""

    def test_roundtrip(self):
        if secretstore._os_backend() is None:
            pytest.skip("no OS credential store on this host")
        try:
            assert secretstore.set_secret(_TEST_NAME, "value-one")
            assert secretstore.get_secret(_TEST_NAME) == "value-one"
            assert secretstore.set_secret(_TEST_NAME, "value-two")  # rotation
            assert secretstore.get_secret(_TEST_NAME) == "value-two"
        finally:
            secretstore.delete_secret(_TEST_NAME)
        assert secretstore.get_secret(_TEST_NAME) is None

    def test_audit_records_rotation(self, audit_to_tmp):
        if secretstore._os_backend() is None:
            pytest.skip("no OS credential store on this host")
        try:
            secretstore.set_secret(_TEST_NAME, "a")
            secretstore.set_secret(_TEST_NAME, "b")
        finally:
            secretstore.delete_secret(_TEST_NAME)

        events = [json.loads(line)["event"]
                  for line in (audit_to_tmp / "audit.log").read_text().splitlines()]
        assert events == ["write", "rotate", "delete"]
        # Values must never appear in the audit trail
        assert "a" not in {e for e in events}


class TestResolutionChain:
    """get_windows_env: store → legacy (promoted) → process env."""

    def test_store_wins(self, monkeypatch):
        monkeypatch.setattr(secretstore, "get_secret",
                            lambda name: "from-store" if name == _TEST_NAME else None)
        assert get_windows_env(_TEST_NAME) == "from-store"

    def test_legacy_promoted(self, monkeypatch):
        promoted = {}
        monkeypatch.setattr(secretstore, "get_secret", lambda name: None)
        monkeypatch.setattr(secretstore, "migrate_legacy",
                            lambda name, value: promoted.update({name: value}))
        monkeypatch.setattr("core.config._legacy_env_get",
                            lambda name: "legacy-value" if name == _TEST_NAME else None)
        assert get_windows_env(_TEST_NAME) == "legacy-value"
        assert promoted == {_TEST_NAME: "legacy-value"}

    def test_process_env_fallback(self, monkeypatch):
        monkeypatch.setattr(secretstore, "get_secret", lambda name: None)
        monkeypatch.setattr("core.config._legacy_env_get", lambda name: None)
        monkeypatch.setenv(_TEST_NAME, "from-env")
        assert get_windows_env(_TEST_NAME) == "from-env"

    def test_invalid_name_rejected(self):
        assert get_windows_env("not-a-valid-name!") is None
        assert set_windows_env("not-a-valid-name!", "x") is False

    def test_set_updates_process_env(self, monkeypatch):
        monkeypatch.setattr(secretstore, "set_secret", lambda name, value: True)
        monkeypatch.delenv(_TEST_NAME, raising=False)
        assert set_windows_env(_TEST_NAME, "sv") is True
        assert os.environ[_TEST_NAME] == "sv"

    def test_set_falls_back_to_legacy_without_store(self, monkeypatch):
        monkeypatch.setattr(secretstore, "set_secret", lambda name, value: False)
        calls = {}
        monkeypatch.setattr("core.config._legacy_env_set",
                            lambda name, value: calls.update({name: value}) or True)
        assert set_windows_env(_TEST_NAME, "lv") is True
        assert calls == {_TEST_NAME: "lv"}


class TestCloudReadThrough:
    def test_vault_lookup_parses_cli_output(self, monkeypatch):
        class R:
            returncode, stdout, stderr = 0, "cloud-secret\n", ""
        monkeypatch.setattr(secretstore.shutil, "which", lambda cmd: "/bin/" + cmd)
        monkeypatch.setattr(secretstore.subprocess, "run", lambda *a, **k: R())
        value = secretstore._cloud_get("MY_KEY", {"cloud_provider": "vault"})
        assert value == "cloud-secret"

    def test_unconfigured_cloud_returns_none(self):
        assert secretstore._cloud_get("MY_KEY", {"cloud_provider": "none"}) is None


class TestWindowsBlobEncoding:
    def test_utf16_roundtrip(self):
        if platform.system() != "Windows" or not secretstore.HAS_WIN32CRED:
            pytest.skip("Windows credential manager unavailable")
        try:
            secretstore._win_set(_TEST_NAME, "påsswörd-ünïcode")
            assert secretstore._win_get(_TEST_NAME) == "påsswörd-ünïcode"
        finally:
            secretstore._win_delete(_TEST_NAME)
