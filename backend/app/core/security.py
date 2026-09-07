"""Security primitives: password hashing, JWT access tokens, refresh token
family lifecycle, API keys, and symmetric encryption for provider secrets.

Design notes (see docs/ARCHITECTURE.md §8):
- argon2id for passwords.
- Access token: short-lived JWT, stateless.
- Refresh token: opaque JWT (jti) persisted in ``refresh_tokens`` with a
  family_id; refresh rotates the token and reuse of a rotated-out token
  revokes the whole family (theft detection).
- API keys: ``ais_<8 prefix><24 secret>``; only sha256 hash is stored.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt as pyjwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import settings

_pwd = PasswordHasher()  # argon2id defaults (m=64MiB, t=3, p=4)
_fernet: Fernet | None = None


# ---------- passwords ----------


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ---------- JWT ----------

TokenType = Literal["access", "refresh"]


def _encode(payload: dict[str, Any]) -> str:
    return pyjwt.encode(payload, settings.effective_jwt_secret(), algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected: TokenType) -> dict[str, Any]:
    """Decode + validate; raises ``pyjwt.PyJWTError`` on any problem."""
    payload: dict[str, Any] = pyjwt.decode(
        token, settings.effective_jwt_secret(), algorithms=[settings.jwt_algorithm]
    )
    if payload.get("typ") != expected:
        raise pyjwt.InvalidTokenError(f"expected {expected} token")
    return payload


def create_access_token(user_id: str, role_codes: list[str]) -> str:
    now = datetime.now(UTC)
    return _encode(
        {
            "sub": user_id,
            "roles": role_codes,
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "jti": uuid.uuid4().hex,
        }
    )


def create_refresh_token() -> tuple[str, str, str]:
    """Returns (token, jti, family_id)."""
    family_id = uuid.uuid4().hex
    jti = uuid.uuid4().hex
    now = datetime.now(UTC)
    token = _encode(
        {
            "typ": "refresh",
            "iat": now,
            "exp": now + timedelta(days=settings.refresh_token_days),
            "jti": jti,
            "fam": family_id,
        }
    )
    return token, jti, family_id


# ---------- API keys ----------


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext, prefix, sha256_hash). Plaintext shown exactly once."""
    prefix = "ais_" + secrets.token_hex(4)  # 12 chars, display only
    secret = secrets.token_hex(24)  # 48 chars
    plaintext = f"{prefix}_{secret}"
    return plaintext, prefix, hashlib.sha256(plaintext.encode()).hexdigest()


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


# ---------- symmetric encryption (provider secrets at rest) ----------


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.effective_fernet_key())
    return _fernet


def encrypt_secret(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(cipher: str) -> str:
    return _get_fernet().decrypt(cipher.encode()).decode()
