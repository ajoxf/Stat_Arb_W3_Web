"""
JWT (JSON Web Token) handler for API authentication.

Provides stateless authentication for API endpoints.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple

import jwt
from flask import current_app

logger = logging.getLogger(__name__)


class JWTHandler:
    """
    JWT token generation and validation.

    Features:
    - Access tokens (short-lived)
    - Refresh tokens (long-lived)
    - Token blacklisting support
    - Secure claims handling
    """

    # Token lifetimes
    ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    def __init__(self, secret_key: str, algorithm: str = 'HS256'):
        """
        Initialize JWT handler.

        Args:
            secret_key: Secret key for signing tokens
            algorithm: JWT algorithm (default HS256)
        """
        self.secret_key = secret_key
        self.algorithm = algorithm

        # In production, use Redis for blacklist
        self._blacklist: set = set()

    def create_access_token(
        self,
        user_id: int,
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create an access token for a user.

        Args:
            user_id: The user's ID
            additional_claims: Optional additional claims to include

        Returns:
            JWT access token string
        """
        now = datetime.now(timezone.utc)
        expires = now + self.ACCESS_TOKEN_EXPIRES

        payload = {
            'sub': str(user_id),
            'type': 'access',
            'iat': now,
            'exp': expires,
            'nbf': now,
        }

        if additional_claims:
            payload.update(additional_claims)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: int) -> str:
        """
        Create a refresh token for a user.

        Refresh tokens are used to obtain new access tokens.

        Args:
            user_id: The user's ID

        Returns:
            JWT refresh token string
        """
        now = datetime.now(timezone.utc)
        expires = now + self.REFRESH_TOKEN_EXPIRES

        payload = {
            'sub': str(user_id),
            'type': 'refresh',
            'iat': now,
            'exp': expires,
            'nbf': now,
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_token_pair(
        self,
        user_id: int,
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        Create both access and refresh tokens.

        Args:
            user_id: The user's ID
            additional_claims: Optional additional claims for access token

        Returns:
            Dictionary with 'access_token' and 'refresh_token'
        """
        return {
            'access_token': self.create_access_token(user_id, additional_claims),
            'refresh_token': self.create_refresh_token(user_id),
            'token_type': 'Bearer',
            'expires_in': int(self.ACCESS_TOKEN_EXPIRES.total_seconds()),
        }

    def verify_token(
        self,
        token: str,
        token_type: str = 'access',
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Verify and decode a JWT token.

        Args:
            token: The JWT token string
            token_type: Expected token type ('access' or 'refresh')

        Returns:
            Tuple of (is_valid, payload, error_message)
        """
        try:
            # Decode and verify token
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={
                    'require': ['sub', 'type', 'iat', 'exp'],
                }
            )

            # Verify token type
            if payload.get('type') != token_type:
                return False, None, f"Invalid token type. Expected {token_type}"

            # Check blacklist
            jti = payload.get('jti')
            if jti and jti in self._blacklist:
                return False, None, "Token has been revoked"

            return True, payload, None

        except jwt.ExpiredSignatureError:
            return False, None, "Token has expired"
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid JWT token: %s", str(e))
            return False, None, "Invalid token"

    def refresh_access_token(
        self,
        refresh_token: str,
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[Dict[str, str]], Optional[str]]:
        """
        Use a refresh token to get a new access token.

        Args:
            refresh_token: The refresh token
            additional_claims: Optional additional claims for new access token

        Returns:
            Tuple of (success, new_tokens, error_message)
        """
        is_valid, payload, error = self.verify_token(refresh_token, token_type='refresh')

        if not is_valid:
            return False, None, error

        user_id = int(payload['sub'])

        # Create new token pair
        tokens = self.create_token_pair(user_id, additional_claims)

        return True, tokens, None

    def revoke_token(self, token: str) -> None:
        """
        Add a token to the blacklist.

        In production, store in Redis with expiry matching token expiry.

        Args:
            token: The token to revoke
        """
        try:
            # Decode without verification to get jti
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={'verify_exp': False}
            )
            jti = payload.get('jti')
            if jti:
                self._blacklist.add(jti)
        except jwt.InvalidTokenError:
            pass  # Token already invalid

    def get_user_id_from_token(self, token: str) -> Optional[int]:
        """
        Extract user ID from a token without full verification.

        Useful for logging/audit purposes.

        Args:
            token: The JWT token

        Returns:
            User ID or None if extraction fails
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={'verify_exp': False}
            )
            return int(payload.get('sub'))
        except (jwt.InvalidTokenError, ValueError, TypeError):
            return None
