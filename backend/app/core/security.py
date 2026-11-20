"""Password hashing (Argon2id) and JWT session tokens."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
_ALGORITHM = "HS256"
_ISSUER = "paynest-api"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    expires_at: datetime


def create_token(user_id: uuid.UUID, session_id: uuid.UUID, secret: str, ttl_minutes: int) -> tuple[str, datetime]:
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(minutes=ttl_minutes)
    token = jwt.encode(
        {"sub": str(user_id), "sid": str(session_id), "iat": now, "exp": expires_at, "iss": _ISSUER},
        secret,
        algorithm=_ALGORITHM,
    )
    return token, expires_at


def decode_token(token: str, secret: str) -> TokenClaims:
    """Raise jwt.PyJWTError on any invalid, expired or tampered token."""
    data = jwt.decode(
        token, secret, algorithms=[_ALGORITHM], issuer=_ISSUER, options={"require": ["exp", "sub", "sid"]}
    )
    return TokenClaims(
        user_id=uuid.UUID(data["sub"]),
        session_id=uuid.UUID(data["sid"]),
        expires_at=datetime.fromtimestamp(data["exp"], tz=UTC),
    )
