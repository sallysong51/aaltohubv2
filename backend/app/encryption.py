"""
Encryption utilities for Telethon session storage.

Security properties:
  - Key derivation: PBKDF2-HMAC-SHA256 with 600K iterations + application salt
  - Encryption: AES-256-GCM with random 12-byte nonce
  - Authenticated data: user_id bound as AAD (prevents session blob swapping)
  - No key hash exposed (prevents offline brute-force targeting)
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from app.config import settings

# Fixed application salt — prevents rainbow tables across deployments.
# This is NOT a secret; its purpose is domain separation.
_APP_SALT = b"aaltohub-v2-session-encryption-salt"

# OWASP 2024 recommendation for PBKDF2-HMAC-SHA256
_KDF_ITERATIONS = 600_000

# Version tag stored in key_hash column to identify encryption scheme
ENCRYPTION_VERSION = "v2-pbkdf2"


class SessionEncryption:
    """AES-256-GCM encryption for Telethon sessions with proper KDF."""

    def __init__(self):
        self.key = self._derive_key(settings.ENCRYPTION_KEY)
        self.aesgcm = AESGCM(self.key)

    def _derive_key(self, password: str) -> bytes:
        """Derive a 32-byte key using PBKDF2-HMAC-SHA256."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_APP_SALT,
            iterations=_KDF_ITERATIONS,
        )
        return kdf.derive(password.encode("utf-8"))

    def encrypt(self, plaintext: str, aad: str | None = None) -> str:
        """
        Encrypt plaintext and return base64-encoded ciphertext.
        Format: base64(nonce + ciphertext)

        Args:
            plaintext: The session string to encrypt.
            aad: Additional authenticated data (e.g., user_id) to bind the
                 ciphertext to a specific context. Decryption will fail if
                 a different aad is provided.
        """
        nonce = os.urandom(12)
        aad_bytes = aad.encode("utf-8") if aad else None
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad_bytes)
        encrypted = base64.b64encode(nonce + ciphertext).decode("utf-8")
        return encrypted

    def decrypt(self, encrypted: str, aad: str | None = None) -> str:
        """
        Decrypt base64-encoded ciphertext and return plaintext.

        Args:
            encrypted: The base64-encoded nonce+ciphertext.
            aad: Must match the aad used during encryption. If the blob was
                 encrypted with a different aad (or no aad), decryption fails.
        """
        data = base64.b64decode(encrypted.encode("utf-8"))
        nonce = data[:12]
        ciphertext = data[12:]
        aad_bytes = aad.encode("utf-8") if aad else None
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, aad_bytes)
        return plaintext.decode("utf-8")

    def get_key_hash(self) -> str:
        """Return an opaque version identifier (not the actual key hash).

        Previously this returned SHA-256 of the raw key, which exposed a
        brute-force verification target. Now returns a version string that
        identifies the encryption scheme without leaking key material.
        """
        return ENCRYPTION_VERSION


# Legacy decryptor for migrating sessions encrypted with the old scheme
class _LegacySessionEncryption:
    """Old SHA-256 key derivation (no salt, no iterations). For migration only."""

    def __init__(self):
        digest = hashes.Hash(hashes.SHA256())
        digest.update(settings.ENCRYPTION_KEY.encode("utf-8"))
        key = digest.finalize()
        self.aesgcm = AESGCM(key)

    def decrypt(self, encrypted: str) -> str:
        data = base64.b64decode(encrypted.encode("utf-8"))
        nonce = data[:12]
        ciphertext = data[12:]
        # Old scheme used None for AAD
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")


_legacy_encryption: _LegacySessionEncryption | None = None


def get_legacy_encryption() -> _LegacySessionEncryption:
    """Lazy-init legacy decryptor (only needed during migration)."""
    global _legacy_encryption
    if _legacy_encryption is None:
        _legacy_encryption = _LegacySessionEncryption()
    return _legacy_encryption


# Global encryption instance
session_encryption = SessionEncryption()
