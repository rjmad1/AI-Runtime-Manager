# core/secret_ref.py
# Resolve environment-variable references in settings values (e.g. litellm.api_key).
# Pure stdlib. Resolved values are returned to the caller only; never write them back to config or logs.

import os
import re
from typing import Optional

_REF = re.compile(r"^(?:os\.environ/([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\})$")


class MissingSecretError(RuntimeError):
    """A settings value references an environment variable that is unset or empty."""


def env_ref_name(value: object) -> Optional[str]:
    """Return the variable name if value is an env reference, else None."""
    if not isinstance(value, str):
        return None
    m = _REF.match(value.strip())
    return (m.group(1) or m.group(2)) if m else None


def resolve_secret(value: object, default: str = "") -> str:
    """Resolve a settings value. Plain values pass through; env references are read from the
    environment and fail closed (MissingSecretError, message names the variable only) if unset/empty.
    A missing/empty value returns default."""
    name = env_ref_name(value)
    if name is None:
        return value if isinstance(value, str) and value else default
    resolved = os.environ.get(name, "")
    if not resolved:
        raise MissingSecretError(f"Environment variable {name} is not set (referenced by settings)")
    return resolved
