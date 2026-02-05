"""
Exchange credential management service.

Handles secure storage and retrieval of user exchange API keys.

SECURITY CRITICAL:
- Keys are encrypted using AES-256-GCM
- Keys are decrypted only when needed and never logged
- Encryption uses per-user derived keys
"""

import logging
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone

from app.database import db, User, UserExchange
from app.database.models import ExchangeType, ExchangeRole
from app.security import EncryptionService

logger = logging.getLogger(__name__)


class ExchangeService:
    """
    Service for managing user exchange credentials.

    Provides secure storage and retrieval of API keys using
    AES-256-GCM encryption with per-user key derivation.
    """

    def __init__(self, encryption_service: EncryptionService):
        """
        Initialize exchange service.

        Args:
            encryption_service: Encryption service for API key encryption
        """
        self.encryption = encryption_service

    def add_exchange(
        self,
        user: User,
        name: str,
        exchange_type: ExchangeType,
        api_key: str,
        secret_key: str,
        passphrase: Optional[str] = None,
        is_testnet: bool = True,
        role: ExchangeRole = ExchangeRole.BOTH,
    ) -> Tuple[bool, str, Optional[UserExchange]]:
        """
        Add a new exchange for a user.

        API keys are encrypted before storage.

        Args:
            user: The user adding the exchange
            name: Friendly name for the exchange
            exchange_type: Type of exchange (OKX, Binance, etc.)
            api_key: Exchange API key
            secret_key: Exchange secret key
            passphrase: Exchange passphrase (OKX only)
            is_testnet: Whether this is a testnet/demo account
            role: Role of exchange (spot, futures, both)

        Returns:
            Tuple of (success, message, exchange)
        """
        try:
            # Encrypt credentials using user's encryption salt
            encrypted_api_key = self.encryption.encrypt(api_key, user.encryption_salt)
            encrypted_secret = self.encryption.encrypt(secret_key, user.encryption_salt)
            encrypted_passphrase = None
            if passphrase:
                encrypted_passphrase = self.encryption.encrypt(passphrase, user.encryption_salt)

            # Create exchange record
            exchange = UserExchange(
                user_id=user.id,
                name=name,
                exchange_type=exchange_type,
                encrypted_api_key=encrypted_api_key,
                encrypted_secret_key=encrypted_secret,
                encrypted_passphrase=encrypted_passphrase,
                is_testnet=is_testnet,
                role=role,
                connection_status='disconnected',
            )

            db.session.add(exchange)
            db.session.commit()

            # Log (without sensitive data)
            logger.info(
                "Exchange added: user_id=%d, exchange=%s, testnet=%s",
                user.id, exchange_type.value, is_testnet
            )

            return True, "Exchange added successfully", exchange

        except Exception as e:
            db.session.rollback()
            logger.error("Failed to add exchange: %s", str(e))
            return False, "Failed to add exchange", None

    def get_decrypted_credentials(
        self,
        user: User,
        exchange: UserExchange,
    ) -> Optional[Dict[str, str]]:
        """
        Get decrypted exchange credentials.

        SECURITY: Only call this when you need to make API calls.
        Never log or store the returned credentials.

        Args:
            user: The user who owns the exchange
            exchange: The exchange record

        Returns:
            Dictionary with api_key, secret_key, and passphrase (if exists)
            or None if decryption fails
        """
        if exchange.user_id != user.id:
            logger.error("User ID mismatch when decrypting credentials")
            return None

        try:
            credentials = {
                'api_key': self.encryption.decrypt(
                    exchange.encrypted_api_key,
                    user.encryption_salt
                ),
                'secret_key': self.encryption.decrypt(
                    exchange.encrypted_secret_key,
                    user.encryption_salt
                ),
            }

            if exchange.encrypted_passphrase:
                credentials['passphrase'] = self.encryption.decrypt(
                    exchange.encrypted_passphrase,
                    user.encryption_salt
                )

            return credentials

        except ValueError as e:
            logger.error("Failed to decrypt credentials: %s", str(e))
            return None

    def update_exchange(
        self,
        user: User,
        exchange_id: int,
        name: Optional[str] = None,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        passphrase: Optional[str] = None,
        is_testnet: Optional[bool] = None,
        role: Optional[ExchangeRole] = None,
    ) -> Tuple[bool, str]:
        """
        Update exchange credentials or settings.

        Args:
            user: The user
            exchange_id: Exchange record ID
            name: New friendly name
            api_key: New API key (will be encrypted)
            secret_key: New secret key (will be encrypted)
            passphrase: New passphrase (will be encrypted)
            is_testnet: Update testnet setting
            role: Update role

        Returns:
            Tuple of (success, message)
        """
        exchange = UserExchange.query.filter_by(
            id=exchange_id,
            user_id=user.id
        ).first()

        if not exchange:
            return False, "Exchange not found"

        try:
            if name is not None:
                exchange.name = name

            if api_key is not None:
                exchange.encrypted_api_key = self.encryption.encrypt(
                    api_key, user.encryption_salt
                )

            if secret_key is not None:
                exchange.encrypted_secret_key = self.encryption.encrypt(
                    secret_key, user.encryption_salt
                )

            if passphrase is not None:
                exchange.encrypted_passphrase = self.encryption.encrypt(
                    passphrase, user.encryption_salt
                ) if passphrase else None

            if is_testnet is not None:
                exchange.is_testnet = is_testnet

            if role is not None:
                exchange.role = role

            db.session.commit()

            logger.info(
                "Exchange updated: user_id=%d, exchange_id=%d",
                user.id, exchange_id
            )

            return True, "Exchange updated successfully"

        except Exception as e:
            db.session.rollback()
            logger.error("Failed to update exchange: %s", str(e))
            return False, "Failed to update exchange"

    def delete_exchange(
        self,
        user: User,
        exchange_id: int,
    ) -> Tuple[bool, str]:
        """
        Delete an exchange.

        Args:
            user: The user
            exchange_id: Exchange record ID

        Returns:
            Tuple of (success, message)
        """
        exchange = UserExchange.query.filter_by(
            id=exchange_id,
            user_id=user.id
        ).first()

        if not exchange:
            return False, "Exchange not found"

        try:
            db.session.delete(exchange)
            db.session.commit()

            logger.info(
                "Exchange deleted: user_id=%d, exchange_id=%d",
                user.id, exchange_id
            )

            return True, "Exchange deleted successfully"

        except Exception as e:
            db.session.rollback()
            logger.error("Failed to delete exchange: %s", str(e))
            return False, "Failed to delete exchange"

    def get_user_exchanges(self, user: User) -> List[UserExchange]:
        """
        Get all exchanges for a user.

        Args:
            user: The user

        Returns:
            List of exchange records (without decrypted credentials)
        """
        return UserExchange.query.filter_by(user_id=user.id).all()

    def set_active_exchange(
        self,
        user: User,
        exchange_id: int,
        is_active: bool,
    ) -> Tuple[bool, str]:
        """
        Set exchange as active/inactive for trading.

        Args:
            user: The user
            exchange_id: Exchange record ID
            is_active: Whether to activate

        Returns:
            Tuple of (success, message)
        """
        exchange = UserExchange.query.filter_by(
            id=exchange_id,
            user_id=user.id
        ).first()

        if not exchange:
            return False, "Exchange not found"

        try:
            exchange.is_active = is_active
            db.session.commit()

            return True, f"Exchange {'activated' if is_active else 'deactivated'}"

        except Exception as e:
            db.session.rollback()
            logger.error("Failed to update exchange active status: %s", str(e))
            return False, "Failed to update exchange"

    def update_connection_status(
        self,
        exchange: UserExchange,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Update exchange connection status.

        Args:
            exchange: The exchange record
            status: Connection status (connected, disconnected, error)
            error: Error message if status is error
        """
        try:
            exchange.connection_status = status
            exchange.last_error = error
            if status == 'connected':
                exchange.last_connected_at = datetime.now(timezone.utc)
            db.session.commit()
        except Exception as e:
            logger.error("Failed to update connection status: %s", str(e))
            db.session.rollback()

    def rotate_user_encryption_key(
        self,
        user: User,
    ) -> Tuple[bool, str]:
        """
        Rotate encryption key for a user's credentials.

        Re-encrypts all API keys with a new salt.
        Call this if user's encryption salt is compromised.

        Args:
            user: The user

        Returns:
            Tuple of (success, message)
        """
        from app.security import KeyDerivation

        exchanges = self.get_user_exchanges(user)

        if not exchanges:
            return True, "No exchanges to rotate"

        try:
            # Decrypt all credentials with old salt
            decrypted_credentials = []
            for exchange in exchanges:
                creds = self.get_decrypted_credentials(user, exchange)
                if creds is None:
                    return False, f"Failed to decrypt credentials for {exchange.name}"
                decrypted_credentials.append((exchange, creds))

            # Generate new salt
            new_salt = KeyDerivation.generate_salt()

            # Re-encrypt all credentials with new salt
            for exchange, creds in decrypted_credentials:
                exchange.encrypted_api_key = self.encryption.encrypt(
                    creds['api_key'], new_salt
                )
                exchange.encrypted_secret_key = self.encryption.encrypt(
                    creds['secret_key'], new_salt
                )
                if creds.get('passphrase'):
                    exchange.encrypted_passphrase = self.encryption.encrypt(
                        creds['passphrase'], new_salt
                    )

            # Update user's salt
            user.encryption_salt = new_salt
            db.session.commit()

            logger.info("Rotated encryption key for user_id=%d", user.id)
            return True, "Encryption key rotated successfully"

        except Exception as e:
            db.session.rollback()
            logger.error("Failed to rotate encryption key: %s", str(e))
            return False, "Failed to rotate encryption key"
