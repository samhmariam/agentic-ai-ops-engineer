"""Authentication and the active-session token.

Until now, RealThor trusted a ``--user`` flag: whoever passed
``--user analyst_001`` *became* that analyst, with no proof. A flag is a claim,
not an identity. At scale that is a hole — anyone can be anyone.

This module closes it. A caller proves identity with a password, verified
against the ``users`` table, before any context is resolved. Passwords are
stored as salted PBKDF2 hashes (stdlib only). For local development every seeded
user shares ``DEV_PASSWORD`` — a convenience, not a security model; the README
notes bcrypt/argon2 and a real secret store as the production upgrade.
"""

import hashlib
import hmac
import os

from realthor.guardrails import UserContext
from realthor.sessions import get_user

# Fixed development password for every seeded user. Local convenience only.
DEV_PASSWORD = "realthor-dev"

_PBKDF2_ROUNDS = 120_000
_SALT_BYTES = 16


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return a ``salt$hash`` string (both hex) using PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored ``salt$hash``."""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return hmac.compare_digest(candidate.hex(), hash_hex)


def authenticate(app_db_path: str, user_id: str, password: str) -> UserContext | None:
    """Verify credentials and return the caller's ``UserContext``.

    Returns None on unknown/inactive user or wrong password — identity is only
    ever granted after the password checks out, and the role/region access come
    from the database row, never from the caller.
    """
    row = get_user(app_db_path, user_id)
    if row is None:
        return None
    if not verify_password(password, str(row["password_hash"])):
        return None
    return UserContext(
        user_id=str(row["user_id"]),
        role=str(row["role"]),
        region_access=str(row["region_access"]),
    )
