"""Symmetric encryption for vault values and raw source records.

Local/dev uses a Fernet key from PII_VAULT_KEY. In AWS the key is a KMS-managed data key per
region (Phase 7); the interface stays the same.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().pii_vault_key.get_secret_value().encode())


def encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt(token: bytes) -> str:
    return _fernet().decrypt(token).decode("utf-8")
