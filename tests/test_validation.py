# tests/test_validation.py
# Unit tests for core/validation.py — provider key validation.

import urllib.error
from unittest.mock import MagicMock, patch

from core.validation import validate_provider_key_http


class TestValidateProviderKey:
    """Tests for validate_provider_key_http."""

    def test_empty_key_rejected(self):
        """Empty or very short keys should be rejected immediately."""
        success, msg = validate_provider_key_http("gemini", "")
        assert not success
        assert "short" in msg.lower() or "empty" in msg.lower()

    def test_short_key_rejected(self):
        """Keys shorter than 8 characters should be rejected."""
        success, msg = validate_provider_key_http("groq", "abc")
        assert not success

    def test_gemini_uses_header_not_url(self):
        """Gemini validation should use x-goog-api-key header, NOT URL query param."""
        with patch("core.validation.urllib.request.urlopen") as mock_open:
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_response.read.return_value = b'{"candidates":[]}'
            mock_open.return_value = mock_response

            success, msg = validate_provider_key_http("gemini", "fake-api-key-12345678")

            # Verify the request was made
            call_args = mock_open.call_args
            request_obj = call_args[0][0]

            # The URL should NOT contain the API key
            assert "key=" not in request_obj.full_url
            assert "fake-api-key" not in request_obj.full_url

            # The API key should be in the header
            assert request_obj.get_header("X-goog-api-key") == "fake-api-key-12345678"

    def test_groq_uses_bearer_auth(self):
        """Groq validation should use Bearer token auth."""
        with patch("core.validation.urllib.request.urlopen") as mock_open:
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_response.read.return_value = b'{"choices":[]}'
            mock_open.return_value = mock_response

            validate_provider_key_http("groq", "gsk_12345678abcdef")

            call_args = mock_open.call_args
            request_obj = call_args[0][0]
            assert "Bearer gsk_12345678abcdef" in request_obj.get_header("Authorization")

    def test_http_error_returns_failure(self):
        """HTTP errors should return (False, error_message)."""
        with patch("core.validation.urllib.request.urlopen") as mock_open:
            error_body = b'{"error": {"message": "Invalid API key"}}'
            mock_open.side_effect = urllib.error.HTTPError(
                url="https://example.com",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=MagicMock(read=MagicMock(return_value=error_body)),
            )
            success, msg = validate_provider_key_http("gemini", "invalid-key-12345678")
            assert not success
            assert "Invalid API key" in msg or "401" in msg

    def test_unknown_provider_succeeds_with_form_check(self):
        """Unknown providers should pass with a form check message."""
        success, msg = validate_provider_key_http("unknownprovider", "some-valid-key-12345678")
        assert success
        assert "form check" in msg.lower()
