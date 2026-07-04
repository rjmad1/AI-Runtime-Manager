# tests/test_auth.py
# Unit + HTTP integration tests for core/auth.py — authN/authZ, RBAC, JWT.

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from core import auth


@pytest.fixture(autouse=True)
def isolated_stores(monkeypatch, tmp_path):
    """Point user/key stores and the JWT key at a temp dir; fixed JWT secret."""
    monkeypatch.setattr(auth, "USERS_PATH", str(tmp_path / "users.yaml"))
    monkeypatch.setattr(auth, "API_KEYS_PATH", str(tmp_path / "api_keys.yaml"))
    monkeypatch.setattr(auth, "_jwt_key", lambda: b"test-jwt-key")
    monkeypatch.setattr(auth, "audit", lambda *a, **k: None)
    yield tmp_path


class TestUsers:
    def test_create_verify_roundtrip(self):
        assert auth.create_user("alice", "s3cret-pass", "admin")
        assert auth.verify_password("alice", "s3cret-pass") == "admin"
        assert auth.verify_password("alice", "wrong") is None
        assert auth.verify_password("nobody", "s3cret-pass") is None

    def test_invalid_role_rejected(self):
        assert auth.create_user("bob", "pw-eight-chars", "superuser") is False

    def test_list_never_exposes_hashes(self):
        auth.create_user("alice", "s3cret-pass", "viewer")
        info = auth.list_users()["alice"]
        assert set(info) == {"role", "created"}

    def test_delete(self):
        auth.create_user("alice", "s3cret-pass")
        assert auth.delete_user("alice")
        assert not auth.delete_user("alice")


class TestJwt:
    def test_issue_verify_roundtrip(self):
        token = auth.jwt_issue("alice", "operator")
        claims = auth.jwt_verify(token)
        assert claims["sub"] == "alice" and claims["role"] == "operator"

    def test_expired_rejected(self):
        token = auth.jwt_issue("alice", "operator", ttl_seconds=-1)
        assert auth.jwt_verify(token) is None

    def test_tampered_rejected(self):
        token = auth.jwt_issue("alice", "operator")
        h, p, s = token.split(".")
        forged_payload = auth._b64url_encode(
            json.dumps({"sub": "alice", "role": "admin", "exp": 9999999999}).encode())
        assert auth.jwt_verify(f"{h}.{forged_payload}.{s}") is None

    def test_none_alg_rejected(self):
        header = auth._b64url_encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        payload = auth._b64url_encode(json.dumps({"sub": "x", "role": "admin",
                                                  "exp": 9999999999}).encode())
        assert auth.jwt_verify(f"{header}.{payload}.") is None


class TestApiKeys:
    def test_token_returned_once_and_hashed(self, isolated_stores):
        token = auth.create_api_key("ci-bot", "operator", service=True)
        assert token.startswith("airm_")
        stored = (isolated_stores / "api_keys.yaml").read_text()
        assert token not in stored  # only the digest is persisted

    def test_authenticate_and_scope_narrowing(self):
        token = auth.create_api_key("readonly-ops", "operator", scopes=["read"])
        identity = auth.authenticate(token)
        assert identity["perms"] == frozenset({"read"})
        assert auth.authorize(identity, "read")
        assert not auth.authorize(identity, "control")

    def test_service_identity_flag(self):
        token = auth.create_api_key("svc", "viewer", service=True)
        assert auth.authenticate(token)["type"] == "service"

    def test_revoked_key_stops_authenticating(self):
        token = auth.create_api_key("temp", "viewer")
        assert auth.revoke_api_key("temp")
        assert auth.authenticate(token) is None

    def test_garbage_tokens_rejected(self):
        assert auth.authenticate("") is None
        assert auth.authenticate("airm_deadbeef") is None
        assert auth.authenticate("not.a.jwt") is None


class TestHttpRbac:
    """End-to-end: login → JWT → permission enforcement on the control plane."""

    @pytest.fixture()
    def server(self, monkeypatch):
        from core import prompt_server
        monkeypatch.setattr(prompt_server, "_AUTH_TOKEN", "session-token-xyz")
        httpd = HTTPServer(("127.0.0.1", 0), prompt_server.PromptRequestHandler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
        httpd.shutdown()
        httpd.server_close()

    @staticmethod
    def _post(url, path, token=None, body=b"{}"):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url + path, data=body, headers=headers, method="POST")
        return urllib.request.urlopen(req, timeout=5)

    def test_login_and_role_enforcement(self, server, monkeypatch):
        auth.create_user("viewer-user", "password-123", "viewer")

        # Login yields a JWT
        body = json.dumps({"username": "viewer-user", "password": "password-123"}).encode()
        with self._post(server, "/api/auth/login", body=body) as res:
            data = json.loads(res.read())
        assert data["success"] and data["role"] == "viewer"

        # Viewer authenticates fine...
        with self._post(server, "/api/auth/check", token=data["token"]) as res:
            assert res.status == 200

        # ...but lacks 'control' → 403 before any action runs
        called = []
        monkeypatch.setattr("core.prompt_server.manager.cmd_stop", lambda: called.append(1))
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(server, "/api/control", token=data["token"],
                       body=b'{"action":"stop"}')
        assert exc.value.code == 403
        assert called == []

    def test_bad_login_rejected(self, server):
        body = json.dumps({"username": "ghost", "password": "nope-nope"}).encode()
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(server, "/api/auth/login", body=body)
        assert exc.value.code == 401

    def test_session_token_still_full_admin(self, server):
        with self._post(server, "/api/auth/check", token="session-token-xyz") as res:
            assert json.loads(res.read())["success"] is True
