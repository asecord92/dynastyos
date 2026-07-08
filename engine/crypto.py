"""Symmetric encryption for secrets at rest (user-supplied API keys).

Uses Fernet (AES-128-CBC + HMAC) with a single app-wide key from the
`APP_ENCRYPTION_KEY` env var. Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

The key never leaves the backend; ciphertext is what lives in the database.
"""
import os
from cryptography.fernet import Fernet

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.getenv("APP_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "APP_ENCRYPTION_KEY must be set to store or read user API keys"
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
