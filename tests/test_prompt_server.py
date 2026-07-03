# tests/test_prompt_server.py
# Regression tests for dashboard API request protection (anti-CSRF token).

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from core import prompt_server


@pytest.fixture()
def server(monkeypatch):
    """Run the dashboard server on an ephemeral port with a known token."""
    monkeypatch.setattr(prompt_server, "_AUTH_TOKEN", "test-token-123")
    httpd = HTTPServer(("127.0.0.1", 0), prompt_server.PromptRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _post(url, path, token=None, body=b"{}"):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url + path, data=body, headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=5)


def test_post_without_token_rejected(server):
    """State-changing POST without the session token must fail with 401."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, "/api/control", body=b'{"action":"stop"}')
    assert exc.value.code == 401


def test_post_with_wrong_token_rejected(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, "/api/auth/check", token="wrong-token")
    assert exc.value.code == 401


def test_auth_check_with_valid_token_succeeds(server):
    with _post(server, "/api/auth/check", token="test-token-123") as res:
        assert res.status == 200
        assert json.loads(res.read())["success"] is True
