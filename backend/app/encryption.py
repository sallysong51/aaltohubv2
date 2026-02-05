"""
Encryption utilities for Telethon session storage
"""
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import os
from app.config import settings


class SessionEncryption:
    """AES-256-GCM encryption for Telethon sessions"""
    
    def __init__(self):
        # Derive 32-byte key from settings
        self.key = self._derive_key(settings.SESSION_ENCRYPTION_KEY)
        self.aesgcm = AESGCM(self.key)
    
    def _derive_key(self, password: str) -> bytes:
        """Derive a 32-byte key from password using SHA-256"""
        digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
        digest.update(password.encode('utf-8'))
        return digest.finalize()
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext and return base64-encoded ciphertext
        Format: base64(nonce + ciphertext)
        """
        # Generate random 12-byte nonce
        nonce = os.urandom(12)
        
        # Encrypt
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        
        # Combine nonce + ciphertext and encode
        encrypted = base64.b64encode(nonce + ciphertext).decode('utf-8')
        return encrypted
    
    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt base64-encoded ciphertext and return plaintext
        """
        # Decode from base64
        data = base64.b64decode(encrypted.encode('utf-8'))
        
        # Split nonce and ciphertext
        nonce = data[:12]
        ciphertext = data[12:]
        
        # Decrypt
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    
    def get_key_hash(self) -> str:
        """Get SHA-256 hash of encryption key for verification"""
        return hashlib.sha256(self.key).hexdigest()


# Global encryption instance
session_encryption = SessionEncryption()
