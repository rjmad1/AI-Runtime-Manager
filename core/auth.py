# core/auth.py
# Authentication and authorization for the AIRM control plane.
# Local users (PBKDF2), scoped API keys / service identities (hashed at rest),
# HS256 JWTs (stdlib hmac — no crypto dependency), and role-based access
# control. External IdP federation (OAuth2/OIDC/SAML/LDAP) is deliberately
# deferred to the Enterprise Security Integration capability.

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import CONFIG_DIR, load_yaml, log, save_yaml
from .secretstore import audit, get_secret, set_secret

USERS_PATH = os.path.join(CONFIG_DIR, "users.yaml")
API_KEYS_PATH = os.path.join(CONFIG_DIR, "api_keys.yaml")
_JWT_SECRET_NAME = "AIRM_JWT_SECRET"
_JWT_SECRET_FILE = os.path.join(CONFIG_DIR, ".jwt_secret")
_PBKDF2_ITERATIONS = 600_000  # OWASP-recommended floor for PBKDF2-HMAC-SHA256
_API_KEY_PREFIX = "airm_"
JWT_TTL_SECONDS = 12 * 3600

# Role → permission sets. Scoped API keys may further narrow these.
ROLES: Dict[str, frozenset] = {
    "admin": frozenset({"read", "control", "configure", "admin"}),
    "operator": frozenset({"read", "control"}),
    "viewer": frozenset({"read"}),
}


# --- Password hashing ---

def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               _PBKDF2_ITERATIONS).hex()


def create_user(username: str, password: str, role: str = "operator") -> bool:
    """Create or update a local user with a salted PBKDF2 password hash."""
    if role not in ROLES:
        log("ERROR", f"Unknown role '{role}'. Use one of: {', '.join(ROLES)}")
        return False
    if not username or not password:
        log("ERROR", "Username and password are required.")
        return False
    data = load_yaml(USERS_PATH)
    users = data.setdefault("users", {})
    salt = secrets.token_bytes(16)
    existed = username in users
    users[username] = {
        "salt": salt.hex(),
        "hash": _hash_password(password, salt),
        "role": role,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_yaml(data, USERS_PATH)
    audit("user-updated" if existed else "user-created", username, provider="auth")
    return True


def delete_user(username: str) -> bool:
    data = load_yaml(USERS_PATH)
    if username not in data.get("users", {}):
        return False
    del data["users"][username]
    save_yaml(data, USERS_PATH)
    audit("user-deleted", username, provider="auth")
    return True


def list_users() -> Dict[str, Dict[str, Any]]:
    """Users with public fields only (no hashes/salts)."""
    users = load_yaml(USERS_PATH).get("users", {})
    return {name: {"role": u.get("role", "viewer"), "created": u.get("created", "")}
            for name, u in users.items()}


def verify_password(username: str, password: str) -> Optional[str]:
    """Return the user's role on success, None on failure (constant-ish time)."""
    users = load_yaml(USERS_PATH).get("users", {})
    user = users.get(username)
    if not user:
        # Burn comparable CPU so a missing user is not distinguishable by timing
        _hash_password(password, b"airm-dummy-salt.")
        audit("login-failed", username, provider="auth", ok=False)
        return None
    computed = _hash_password(password, bytes.fromhex(user["salt"]))
    if hmac.compare_digest(computed, user["hash"]):
        audit("login", username, provider="auth")
        return user.get("role", "viewer")
    audit("login-failed", username, provider="auth", ok=False)
    return None


# --- JWT (HS256, stdlib only) ---

def _jwt_key() -> bytes:
    """Signing key from the OS credential store, generated on first use.
    Falls back to a locked-down local file when no store is available."""
    key = get_secret(_JWT_SECRET_NAME)
    if key:
        return key.encode("utf-8")
    new_key = secrets.token_hex(32)
    if set_secret(_JWT_SECRET_NAME, new_key):
        return new_key.encode("utf-8")
    if os.path.exists(_JWT_SECRET_FILE):
        with open(_JWT_SECRET_FILE, "r", encoding="utf-8") as f:
            return f.read().strip().encode("utf-8")
    with open(_JWT_SECRET_FILE, "w", encoding="utf-8") as f:
        f.write(new_key)
    try:
        os.chmod(_JWT_SECRET_FILE, 0o600)
    except OSError:
        pass  # Windows: NTFS ACLs already scope the profile directory
    return new_key.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def jwt_issue(subject: str, role: str, ttl_seconds: int = JWT_TTL_SECONDS) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": subject, "role": role, "iss": "airm",
        "iat": int(time.time()), "exp": int(time.time()) + ttl_seconds,
    }).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64url_encode(hmac.new(_jwt_key(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def jwt_verify(token: str) -> Optional[Dict[str, Any]]:
    """Verify signature, algorithm, and expiry. Returns claims or None."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":  # refuse downgraded/none algorithms
            return None
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = hmac.new(_jwt_key(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
            return None
        claims = json.loads(_b64url_decode(payload_b64))
        if claims.get("exp", 0) < time.time():
            return None
        return claims
    except Exception:
        return None


# --- API keys and service identities ---

def create_api_key(name: str, role: str = "operator",
                   scopes: Optional[List[str]] = None, service: bool = False) -> Optional[str]:
    """Create a scoped API key. The token is returned exactly once; only its
    SHA-256 digest is persisted. service=True marks a service identity."""
    if role not in ROLES:
        log("ERROR", f"Unknown role '{role}'. Use one of: {', '.join(ROLES)}")
        return None
    token = _API_KEY_PREFIX + secrets.token_hex(24)
    data = load_yaml(API_KEYS_PATH)
    keys = data.setdefault("keys", [])
    keys.append({
        "id": secrets.token_hex(4),
        "name": name,
        "sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "role": role,
        "scopes": sorted(scopes) if scopes else [],
        "type": "service" if service else "user",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    save_yaml(data, API_KEYS_PATH)
    audit("apikey-created", name, provider="auth")
    return token


def revoke_api_key(name_or_id: str) -> bool:
    data = load_yaml(API_KEYS_PATH)
    keys = data.get("keys", [])
    remaining = [k for k in keys if k.get("name") != name_or_id and k.get("id") != name_or_id]
    if len(remaining) == len(keys):
        return False
    data["keys"] = remaining
    save_yaml(data, API_KEYS_PATH)
    audit("apikey-revoked", name_or_id, provider="auth")
    return True


def list_api_keys() -> List[Dict[str, Any]]:
    """Key metadata only — digests are never exposed."""
    return [{"id": k.get("id"), "name": k.get("name"), "role": k.get("role"),
             "scopes": k.get("scopes", []), "type": k.get("type", "user"),
             "created": k.get("created", "")}
            for k in load_yaml(API_KEYS_PATH).get("keys", [])]


# --- Request authentication / authorization ---

def authenticate(bearer_token: str) -> Optional[Dict[str, Any]]:
    """Resolve a Bearer credential (API key or JWT) into an identity:
    {subject, role, perms, type}. Returns None when invalid."""
    if not bearer_token:
        return None

    if bearer_token.startswith(_API_KEY_PREFIX):
        digest = hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()
        for k in load_yaml(API_KEYS_PATH).get("keys", []):
            if hmac.compare_digest(digest, k.get("sha256", "")):
                role = k.get("role", "viewer")
                perms = ROLES.get(role, frozenset())
                scopes = k.get("scopes") or []
                if scopes:  # scoped token: intersection of role and scopes
                    perms = perms & frozenset(scopes)
                return {"subject": k.get("name", "api-key"), "role": role,
                        "perms": perms, "type": k.get("type", "user")}
        return None

    claims = jwt_verify(bearer_token)
    if claims:
        role = claims.get("role", "viewer")
        return {"subject": claims.get("sub", "jwt"), "role": role,
                "perms": ROLES.get(role, frozenset()), "type": "jwt"}
    return None


def authorize(identity: Optional[Dict[str, Any]], permission: str) -> bool:
    return bool(identity) and permission in identity.get("perms", frozenset())


def has_users() -> bool:
    """Whether any local users exist (bootstrap detection)."""
    return bool(load_yaml(USERS_PATH).get("users"))
