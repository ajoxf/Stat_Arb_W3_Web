"""
AES-256-GCM encryption for API keys with secure key derivation.

Security Features:
- AES-256-GCM authenticated encryption
- Unique IV per encryption (96 bits)
- Key derivation using Argon2id
- Encryption key derived from master key + user-specific salt
- Keys never logged or exposed in error messages

CRITICAL: This module handles sensitive exchange credentials.
Any changes must be carefully reviewed for security implications.
"""

import os
import base64
import secrets
import logging
from typing import Tuple, Optional
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import argon2

logger = logging.getLogger(__name__)


class KeyDerivation:
    """
    Secure key derivation using Argon2id.

    Derives encryption keys from:
    - Master key (from environment/secrets manager)
    - User-specific salt (stored with user record)
    """

    # Argon2id parameters (OWASP recommended for password hashing)
    # Adjusted for key derivation - slightly faster than password hashing
    TIME_COST = 2
    MEMORY_COST = 65536  # 64 MB
    PARALLELISM = 4
    HASH_LEN = 32  # 256 bits for AES-256

    @classmethod
    def generate_salt(cls) -> bytes:
        """Generate a cryptographically secure random salt (16 bytes)."""
        return secrets.token_bytes(16)

    @classmethod
    def derive_key(cls, master_key: bytes, user_salt: bytes) -> bytes:
        """
        Derive a user-specific encryption key from master key and user salt.

        Args:
            master_key: The application master encryption key
            user_salt: User-specific salt (stored with user record)

        Returns:
            32-byte derived key for AES-256
        """
        # Use Argon2id for memory-hard key derivation
        hasher = argon2.low_level.hash_secret_raw(
            secret=master_key,
            salt=user_salt,
            time_cost=cls.TIME_COST,
            memory_cost=cls.MEMORY_COST,
            parallelism=cls.PARALLELISM,
            hash_len=cls.HASH_LEN,
            type=argon2.low_level.Type.ID,
        )
        return hasher

    @classmethod
    def derive_key_simple(cls, master_key: str, salt: bytes) -> bytes:
        """
        Simpler PBKDF2-based derivation for session keys.
        Used for less critical operations where speed matters.
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )
        return kdf.derive(master_key.encode('utf-8'))


@dataclass
class EncryptedData:
    """Container for encrypted data with IV and auth tag."""
    ciphertext: bytes
    iv: bytes
    # GCM includes auth tag in ciphertext

    def to_storage_format(self) -> str:
        """
        Convert to base64 storage format.
        Format: base64(iv + ciphertext)
        """
        combined = self.iv + self.ciphertext
        return base64.b64encode(combined).decode('utf-8')

    @classmethod
    def from_storage_format(cls, data: str) -> 'EncryptedData':
        """
        Parse from base64 storage format.
        """
        combined = base64.b64decode(data.encode('utf-8'))
        # IV is 12 bytes (96 bits) for GCM
        iv = combined[:12]
        ciphertext = combined[12:]
        return cls(ciphertext=ciphertext, iv=iv)


class EncryptionService:
    """
    Handles encryption/decryption of sensitive data using AES-256-GCM.

    Usage:
        service = EncryptionService(master_key)

        # Encrypt API key
        encrypted = service.encrypt(api_key, user_salt)

        # Decrypt API key
        decrypted = service.decrypt(encrypted, user_salt)
    """

    # IV size for GCM (96 bits recommended by NIST)
    IV_SIZE = 12

    def __init__(self, master_key: str):
        """
        Initialize encryption service.

        Args:
            master_key: Application master encryption key (from env/secrets)
        """
        if not master_key:
            raise ValueError("Master encryption key is required")

        # Store master key bytes
        self._master_key = master_key.encode('utf-8') if isinstance(master_key, str) else master_key

        # Validate key length (should be at least 32 chars for security)
        if len(self._master_key) < 32:
            logger.warning("Master key is shorter than recommended 32 characters")

    def _get_user_key(self, user_salt: bytes) -> bytes:
        """Derive user-specific encryption key."""
        return KeyDerivation.derive_key(self._master_key, user_salt)

    def encrypt(self, plaintext: str, user_salt: bytes) -> str:
        """
        Encrypt a string using AES-256-GCM.

        Args:
            plaintext: The string to encrypt (e.g., API key)
            user_salt: User-specific salt for key derivation

        Returns:
            Base64-encoded encrypted data (IV + ciphertext)
        """
        if not plaintext:
            return ""

        # Derive user-specific key
        key = self._get_user_key(user_salt)

        # Generate unique IV
        iv = secrets.token_bytes(self.IV_SIZE)

        # Encrypt with AES-256-GCM
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext.encode('utf-8'), None)

        # Package and return
        encrypted = EncryptedData(ciphertext=ciphertext, iv=iv)
        return encrypted.to_storage_format()

    def decrypt(self, encrypted_data: str, user_salt: bytes) -> str:
        """
        Decrypt a string using AES-256-GCM.

        Args:
            encrypted_data: Base64-encoded encrypted data
            user_salt: User-specific salt for key derivation

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails (invalid data or wrong key)
        """
        if not encrypted_data:
            return ""

        try:
            # Parse encrypted data
            data = EncryptedData.from_storage_format(encrypted_data)

            # Derive user-specific key
            key = self._get_user_key(user_salt)

            # Decrypt
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(data.iv, data.ciphertext, None)

            return plaintext.decode('utf-8')

        except Exception as e:
            # Don't log the actual data - could contain secrets
            logger.error("Decryption failed: authentication error")
            raise ValueError("Decryption failed - invalid data or key") from e

    def rotate_key(
        self,
        encrypted_data: str,
        old_user_salt: bytes,
        new_user_salt: bytes,
    ) -> str:
        """
        Re-encrypt data with a new user salt (for key rotation).

        Args:
            encrypted_data: Currently encrypted data
            old_user_salt: Current user salt
            new_user_salt: New user salt

        Returns:
            Re-encrypted data with new salt
        """
        # Decrypt with old key
        plaintext = self.decrypt(encrypted_data, old_user_salt)

        # Re-encrypt with new key
        return self.encrypt(plaintext, new_user_salt)


class SecureMemory:
    """
    Utilities for secure memory handling.

    Note: Python's memory management makes true secure deletion difficult.
    These are best-effort measures.
    """

    @staticmethod
    def secure_compare(a: bytes, b: bytes) -> bool:
        """
        Constant-time comparison to prevent timing attacks.
        """
        if len(a) != len(b):
            return False

        result = 0
        for x, y in zip(a, b):
            result |= x ^ y

        return result == 0

    @staticmethod
    def clear_string(s: str) -> None:
        """
        Best-effort attempt to clear a string from memory.

        Note: This doesn't guarantee the string is cleared due to
        Python's string interning and garbage collection.
        """
        # Can't truly clear Python strings, but we can try
        # to trigger garbage collection for the object
        del s

    @staticmethod
    def generate_key() -> str:
        """Generate a secure random key for use as master key."""
        return secrets.token_urlsafe(32)
