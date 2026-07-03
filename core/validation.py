# core/validation.py
# Provider API key validation with real HTTP endpoint checks.

import json
import re
import urllib.error
import urllib.request
from typing import Tuple

# Provider name validation pattern
_VALID_PROVIDER_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_provider(provider: str) -> bool:
    """Validate provider name to prevent injection attacks."""
    if not provider or len(provider) > 50:
        return False
    return bool(_VALID_PROVIDER_PATTERN.match(provider))


def validate_provider_key_http(provider: str, api_key: str) -> Tuple[bool, str]:
    """Validate an API key by making a real HTTP request to the provider.

    Returns (success: bool, message: str).
    """
    # Validate provider name
    if not _validate_provider(provider):
        return False, "Invalid provider name."

    if not api_key or len(api_key.strip()) < 8:
        return False, "Key is too short or empty."

    try:
        if provider == "gemini":
            # Use header-based auth instead of URL query parameter to prevent key leakage
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
            body = json.dumps({"contents": [{"parts": [{"text": "Say ok"}]}]}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=10.0):
                return True, "Key is valid."

        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
            body = json.dumps({
                "model": "llama-3.3-70b-specdec",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 1,
            }).encode("utf-8")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0):
                return True, "Key is valid."

        elif provider == "sambanova":
            url = "https://api.sambanova.ai/v1/chat/completions"
            body = json.dumps({
                "model": "Meta-Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 1,
            }).encode("utf-8")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0):
                return True, "Key is valid."

        elif provider == "cerebras":
            url = "https://api.cerebras.ai/v1/chat/completions"
            body = json.dumps({
                "model": "llama3.1-8b",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 1,
            }).encode("utf-8")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0):
                return True, "Key is valid."

        elif provider == "openrouter":
            url = "https://openrouter.ai/api/v1/auth/key"
            headers = {"Authorization": f"Bearer {api_key}"}
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=10.0):
                return True, "Key is valid."

        return True, "Form check succeeded (no live endpoint test implemented)."

    except urllib.error.HTTPError as e:
        try:
            error_data = json.loads(e.read().decode())
            if "error" in error_data and "message" in error_data["error"]:
                return False, error_data["error"]["message"]
        except Exception:
            pass
        return False, f"API rejected credential: HTTP {e.code}"
    except Exception as e:
        return False, f"Network/Connection error: {e}"
