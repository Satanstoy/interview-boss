"""API key encryption service using Fernet."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

_fernet_instance: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        secret = os.getenv("JWT_SECRET", "")
        if not secret:
            raise RuntimeError("JWT_SECRET must be set for API key encryption")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        _fernet_instance = Fernet(key)
    return _fernet_instance


def _reset_fernet() -> None:
    """Reset cached instance (for testing only)."""
    global _fernet_instance
    _fernet_instance = None


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value. Returns ciphertext as a string."""
    if not plaintext:
        return plaintext
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt an encrypted string value.

    If decryption fails, assumes the value is plaintext (migration period)
    and returns it unchanged.
    """
    if not ciphertext:
        return ciphertext
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ciphertext


def is_encrypted(value: str) -> bool:
    """Check if a value looks like a Fernet-encrypted token."""
    if not value or len(value) < 32:
        return False
    try:
        _get_fernet().decrypt(value.encode())
        return True
    except (InvalidToken, Exception):
        return False
