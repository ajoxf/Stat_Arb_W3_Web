"""
Password hashing using Argon2id.

Follows OWASP recommendations for secure password storage.
"""

import secrets
import logging
from typing import Tuple

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash

logger = logging.getLogger(__name__)


class PasswordHasher:
    """
    Secure password hashing using Argon2id.

    Features:
    - Argon2id (winner of Password Hashing Competition)
    - Memory-hard (prevents GPU/ASIC attacks)
    - Configurable parameters following OWASP guidelines
    """

    # OWASP recommended parameters for Argon2id
    # These values balance security with reasonable login times
    TIME_COST = 3          # Number of iterations
    MEMORY_COST = 65536    # 64 MB memory usage
    PARALLELISM = 4        # Parallel threads
    HASH_LENGTH = 32       # Output hash length
    SALT_LENGTH = 16       # Salt length

    def __init__(self):
        """Initialize the password hasher with secure defaults."""
        self._hasher = Argon2Hasher(
            time_cost=self.TIME_COST,
            memory_cost=self.MEMORY_COST,
            parallelism=self.PARALLELISM,
            hash_len=self.HASH_LENGTH,
            salt_len=self.SALT_LENGTH,
            type=Argon2Hasher.Type.ID,  # Argon2id
        )

    def hash_password(self, password: str) -> str:
        """
        Hash a password securely.

        Args:
            password: The plaintext password

        Returns:
            The hashed password in Argon2 format (includes salt and parameters)
        """
        if not password:
            raise ValueError("Password cannot be empty")

        return self._hasher.hash(password)

    def verify_password(self, password: str, hash: str) -> bool:
        """
        Verify a password against a hash.

        Args:
            password: The plaintext password to verify
            hash: The stored Argon2 hash

        Returns:
            True if password matches, False otherwise
        """
        if not password or not hash:
            return False

        try:
            self._hasher.verify(hash, password)
            return True
        except VerifyMismatchError:
            return False
        except (VerificationError, InvalidHash) as e:
            logger.warning("Password verification error: %s", type(e).__name__)
            return False

    def needs_rehash(self, hash: str) -> bool:
        """
        Check if a hash needs to be updated due to parameter changes.

        Useful when upgrading security parameters over time.

        Args:
            hash: The stored Argon2 hash

        Returns:
            True if hash should be regenerated with current parameters
        """
        try:
            return self._hasher.check_needs_rehash(hash)
        except InvalidHash:
            return True

    @staticmethod
    def generate_temp_password(length: int = 16) -> str:
        """
        Generate a secure temporary password.

        Args:
            length: Password length (default 16)

        Returns:
            A cryptographically secure random password
        """
        return secrets.token_urlsafe(length)

    @staticmethod
    def validate_password_strength(password: str) -> Tuple[bool, str]:
        """
        Validate password meets minimum security requirements.

        Requirements:
        - At least 8 characters
        - Contains uppercase letter
        - Contains lowercase letter
        - Contains number
        - Contains special character

        Args:
            password: The password to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(password) < 8:
            return False, "Password must be at least 8 characters"

        if not any(c.isupper() for c in password):
            return False, "Password must contain an uppercase letter"

        if not any(c.islower() for c in password):
            return False, "Password must contain a lowercase letter"

        if not any(c.isdigit() for c in password):
            return False, "Password must contain a number"

        special_chars = set("!@#$%^&*()_+-=[]{}|;:,.<>?")
        if not any(c in special_chars for c in password):
            return False, "Password must contain a special character"

        return True, ""
