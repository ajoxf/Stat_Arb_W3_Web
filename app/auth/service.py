"""
Authentication service for user management.

Handles:
- User registration
- Login/logout
- Password reset
- Email verification
- Session management
"""

import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

from flask import current_app, request
from flask_login import LoginManager, login_user, logout_user, current_user

from app.database import db, User, UserConfig, AuditLog
from app.security import PasswordHasher, KeyDerivation

logger = logging.getLogger(__name__)

# Initialize Flask-Login
login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    """Load user by ID for Flask-Login."""
    return User.query.get(int(user_id))


class AuthService:
    """
    Authentication and user management service.

    Security features:
    - Argon2id password hashing
    - Secure session management
    - Account lockout after failed attempts
    - Audit logging
    """

    # Account lockout settings
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 15

    def __init__(self):
        self.password_hasher = PasswordHasher()
        self._login_attempts: Dict[str, Dict] = {}  # In production, use Redis

    def register_user(
        self,
        email: str,
        password: str,
        name: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[User]]:
        """
        Register a new user.

        Args:
            email: User's email address
            password: User's password
            name: Optional display name

        Returns:
            Tuple of (success, message, user)
        """
        email = email.lower().strip()

        # Validate email format
        if not self._validate_email(email):
            return False, "Invalid email address", None

        # Check if user exists
        existing = User.query.filter_by(email=email).first()
        if existing:
            return False, "Email already registered", None

        # Validate password strength
        is_valid, error_msg = self.password_hasher.validate_password_strength(password)
        if not is_valid:
            return False, error_msg, None

        try:
            # Hash password
            password_hash = self.password_hasher.hash_password(password)

            # Generate encryption salt for user's API keys
            encryption_salt = KeyDerivation.generate_salt()

            # Generate verification token
            verification_token = secrets.token_urlsafe(32)

            # Create user
            user = User(
                email=email,
                password_hash=password_hash,
                encryption_salt=encryption_salt,
                name=name,
                verification_token=verification_token,
                is_verified=False,
            )

            db.session.add(user)
            db.session.flush()  # Get user ID

            # Create default config
            config = UserConfig(user_id=user.id)
            db.session.add(config)

            # Audit log
            self._log_audit(
                user_id=user.id,
                event_type='user.registered',
                event_description=f'New user registered: {email}',
            )

            db.session.commit()

            logger.info("User registered: %s", email)
            return True, "Registration successful", user

        except Exception as e:
            db.session.rollback()
            logger.error("Registration failed: %s", str(e))
            return False, "Registration failed. Please try again.", None

    def login(
        self,
        email: str,
        password: str,
        remember: bool = False,
    ) -> Tuple[bool, str, Optional[User]]:
        """
        Authenticate user and create session.

        Args:
            email: User's email address
            password: User's password
            remember: Whether to remember the session

        Returns:
            Tuple of (success, message, user)
        """
        email = email.lower().strip()

        # Check for account lockout
        if self._is_locked_out(email):
            return False, "Account temporarily locked. Please try again later.", None

        # Find user
        user = User.query.filter_by(email=email).first()

        if not user:
            self._record_failed_attempt(email)
            return False, "Invalid email or password", None

        # Verify password
        if not self.password_hasher.verify_password(password, user.password_hash):
            self._record_failed_attempt(email)
            self._log_audit(
                user_id=user.id,
                event_type='auth.login_failed',
                event_description='Failed login attempt',
            )
            return False, "Invalid email or password", None

        # Check if account is active
        if not user.is_active:
            return False, "Account is disabled", None

        # Check if password needs rehash (security parameters updated)
        if self.password_hasher.needs_rehash(user.password_hash):
            user.password_hash = self.password_hasher.hash_password(password)
            db.session.commit()

        # Clear failed attempts
        self._clear_failed_attempts(email)

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()

        # Create session
        login_user(user, remember=remember)

        # Audit log
        self._log_audit(
            user_id=user.id,
            event_type='auth.login_success',
            event_description='Successful login',
        )

        logger.info("User logged in: %s", email)
        return True, "Login successful", user

    def logout(self) -> None:
        """Log out current user."""
        if current_user.is_authenticated:
            self._log_audit(
                user_id=current_user.id,
                event_type='auth.logout',
                event_description='User logged out',
            )
            logout_user()

    def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
    ) -> Tuple[bool, str]:
        """
        Change user's password.

        Args:
            user: The user
            current_password: Current password for verification
            new_password: New password

        Returns:
            Tuple of (success, message)
        """
        # Verify current password
        if not self.password_hasher.verify_password(current_password, user.password_hash):
            return False, "Current password is incorrect"

        # Validate new password
        is_valid, error_msg = self.password_hasher.validate_password_strength(new_password)
        if not is_valid:
            return False, error_msg

        # Check new password is different
        if self.password_hasher.verify_password(new_password, user.password_hash):
            return False, "New password must be different from current password"

        try:
            # Hash new password
            user.password_hash = self.password_hasher.hash_password(new_password)
            db.session.commit()

            self._log_audit(
                user_id=user.id,
                event_type='auth.password_changed',
                event_description='Password changed',
            )

            logger.info("Password changed for user: %s", user.email)
            return True, "Password changed successfully"

        except Exception as e:
            db.session.rollback()
            logger.error("Password change failed: %s", str(e))
            return False, "Failed to change password"

    def initiate_password_reset(self, email: str) -> Tuple[bool, str, Optional[str]]:
        """
        Initiate password reset process.

        Returns:
            Tuple of (success, message, reset_token)
        """
        email = email.lower().strip()
        user = User.query.filter_by(email=email).first()

        if not user:
            # Don't reveal whether email exists
            return True, "If an account exists, a reset link will be sent.", None

        # Generate reset token
        reset_token = secrets.token_urlsafe(32)

        # In production, store token with expiry in database or cache
        # For now, return it (would be sent via email)

        self._log_audit(
            user_id=user.id,
            event_type='auth.password_reset_requested',
            event_description='Password reset requested',
        )

        return True, "If an account exists, a reset link will be sent.", reset_token

    def verify_email(self, token: str) -> Tuple[bool, str]:
        """
        Verify user's email address.

        Args:
            token: Verification token

        Returns:
            Tuple of (success, message)
        """
        user = User.query.filter_by(verification_token=token).first()

        if not user:
            return False, "Invalid verification token"

        user.is_verified = True
        user.verification_token = None
        db.session.commit()

        self._log_audit(
            user_id=user.id,
            event_type='auth.email_verified',
            event_description='Email verified',
        )

        return True, "Email verified successfully"

    def _is_locked_out(self, email: str) -> bool:
        """Check if account is locked due to failed attempts."""
        attempts = self._login_attempts.get(email, {})
        if attempts.get('count', 0) >= self.MAX_LOGIN_ATTEMPTS:
            lockout_until = attempts.get('lockout_until')
            if lockout_until and datetime.now(timezone.utc) < lockout_until:
                return True
            else:
                # Lockout expired
                self._clear_failed_attempts(email)
        return False

    def _record_failed_attempt(self, email: str) -> None:
        """Record a failed login attempt."""
        if email not in self._login_attempts:
            self._login_attempts[email] = {'count': 0}

        self._login_attempts[email]['count'] += 1

        if self._login_attempts[email]['count'] >= self.MAX_LOGIN_ATTEMPTS:
            self._login_attempts[email]['lockout_until'] = (
                datetime.now(timezone.utc) +
                timedelta(minutes=self.LOCKOUT_DURATION_MINUTES)
            )
            logger.warning("Account locked out: %s", email)

    def _clear_failed_attempts(self, email: str) -> None:
        """Clear failed login attempts."""
        if email in self._login_attempts:
            del self._login_attempts[email]

    def _validate_email(self, email: str) -> bool:
        """Basic email validation."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    def _log_audit(
        self,
        user_id: Optional[int],
        event_type: str,
        event_description: str,
    ) -> None:
        """Create audit log entry."""
        try:
            audit = AuditLog(
                user_id=user_id,
                event_type=event_type,
                event_description=event_description,
                ip_address=request.remote_addr if request else None,
                user_agent=request.user_agent.string if request and request.user_agent else None,
            )
            db.session.add(audit)
            # Don't commit here - let caller commit with main transaction
        except Exception as e:
            logger.error("Failed to create audit log: %s", str(e))
