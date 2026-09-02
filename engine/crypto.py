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


def looks_encrypted(value: str) -> bool:
    """Whether `value` is one of our Fernet tokens. Fernet v1 tokens are
    urlsafe-base64 of a payload whose first byte is 0x80, which always renders
    as the prefix "gAAAAA" — no Fantrax Secret ID looks like that."""
    return bool(value) and value.startswith("gAAAAA")


def decrypt_tolerant(value: str | None) -> str | None:
    """Decrypt a column that may still hold plaintext from before it was
    encrypted, returning it either way.

    Lets a secret be encrypted in place without a backfill migration or a
    flag day: rows written before the change keep working and are re-written
    encrypted the next time something saves them. Mirrors how `_select_id_map`
    tolerates `player_id_map.age` being absent pre-migration.

    Anything that fails to decrypt is returned as-is rather than raising — an
    unreadable secret should degrade to "Fantrax rejects it", not a 500 that
    strands the user with no way to re-enter it.
    """
    if not value:
        return None
    if not looks_encrypted(value):
        return value  # written before this column was encrypted
    try:
        return decrypt(value)
    except Exception:
        return None
