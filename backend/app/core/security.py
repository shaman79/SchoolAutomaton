"""Security primitives: resume-code generation, hashing, admin JWT, and Fernet secret encryption.

Learner auth = opaque server-issued resume code (we store only its sha256 hash).
Admin auth = username/password (Argon2id) → short-lived JWT. Two fully separate realms (SPEC §5).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

# Crockford base32 alphabet (no I, L, O, U — avoids ambiguity for hand-typed codes).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ph = PasswordHasher()


# --------------------------------------------------------------------------- resume codes
def generate_resume_code() -> str:
    """Return an 8-char Crockford base32 code grouped as ``XXXX-XXXX`` (e.g. ``K7QF-2M9X``)."""
    chars = "".join(secrets.choice(_CROCKFORD) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def normalize_resume_code(code: str) -> str:
    """Uppercase, strip dashes/spaces, map common look-alikes so user-typed codes match."""
    cleaned = code.strip().upper().replace("-", "").replace(" ", "")
    table = str.maketrans({"I": "1", "L": "1", "O": "0", "U": "V"})
    return cleaned.translate(table)


def hash_resume_code(code: str) -> str:
    """sha256 of the normalized code. Lookups use this hash; the raw code is never stored."""
    return hashlib.sha256(normalize_resume_code(code).encode()).hexdigest()


# --------------------------------------------------------------------------- generic hashing
def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def salted_hash(value: str, *, salt: str | None = None) -> str:
    """Keyed hash for IP/device — uses APP_SECRET so hashes aren't reversible via rainbow tables."""
    key = (salt or settings.app_secret).encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- admin passwords
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


# --------------------------------------------------------------------------- admin JWT
def create_admin_token(*, subject: str, role: str = "admin") -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        "realm": "admin",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_admin_token(token: str) -> dict:
    """Raise jwt.PyJWTError on invalid/expired tokens."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    if payload.get("realm") != "admin":
        raise jwt.InvalidTokenError("wrong realm")
    return payload


# --------------------------------------------------------------------------- secret encryption
def _fernet() -> Fernet:
    return Fernet(settings.fernet_key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
