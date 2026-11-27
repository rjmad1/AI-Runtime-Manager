# tests/test_secret_ref.py
# Dummy-value tests for env-reference resolution. No real secrets. unittest style (runs under pytest too).
import importlib.util
import os
import pathlib
import re
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("secret_ref_under_test", _ROOT / "core" / "secret_ref.py")
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

DUMMY = "dummy-not-a-secret-123"
REFS = ["os.environ/AIRM_TEST_KEY", "${AIRM_TEST_KEY}"]


def _env(**kw):
    base = {k: v for k, v in os.environ.items() if k != "AIRM_TEST_KEY"}
    base.update(kw)
    return mock.patch.dict(os.environ, base, clear=True)


class TestResolver(unittest.TestCase):
    def test_plain_and_default(self):
        self.assertEqual(sr.resolve_secret("plain"), "plain")
        self.assertEqual(sr.resolve_secret("", "dflt"), "dflt")
        self.assertEqual(sr.resolve_secret(None, "dflt"), "dflt")

    def test_reference_resolves(self):
        for ref in REFS:
            with _env(AIRM_TEST_KEY=DUMMY):
                self.assertEqual(sr.resolve_secret(ref), DUMMY)

    def test_missing_fails_closed_and_ignores_default(self):
        for ref in REFS:
            with _env():
                with self.assertRaises(sr.MissingSecretError) as cm:
                    sr.resolve_secret(ref, "sk-litellm-key")
                self.assertIn("AIRM_TEST_KEY", str(cm.exception))

    def test_empty_env_fails_closed(self):
        with _env(AIRM_TEST_KEY=""):
            with self.assertRaises(sr.MissingSecretError):
                sr.resolve_secret("os.environ/AIRM_TEST_KEY")

    def test_lookalikes_are_literal(self):
        for v in ["os.environ/", "prefix-${X}", "sk-abc"]:
            self.assertIsNone(sr.env_ref_name(v))


class TestConsumersWired(unittest.TestCase):
    """The four api_key consumers (config.py ~562, diagnostics.py ~100, process.py ~307 and ~330)."""

    def _src(self, name):
        return (_ROOT / "core" / name).read_text(encoding="utf-8")

    def test_no_literal_reads_remain(self):
        for name in ("diagnostics.py", "process.py"):
            src = self._src(name)
            self.assertNotRegex(src, r'(?<!resolve_secret\()settings\.get\("litellm", \{\}\)\.get\("api_key"')
        self.assertEqual(self._src("process.py").count("resolve_secret(settings"), 2)
        self.assertEqual(self._src("diagnostics.py").count("resolve_secret(settings"), 1)

    def test_config_does_not_generate_or_persist_for_reference(self):
        src = self._src("config.py")
        self.assertRegex(src, r"if env_ref_name\(litellm_key\):\n\s+#[^\n]*\n\s+resolve_secret\(litellm_key\)\n\s+elif not litellm_key:")


if __name__ == "__main__":
    unittest.main()
