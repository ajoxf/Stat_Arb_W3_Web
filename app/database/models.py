"""
SQLAlchemy models for multi-tenant crypto arbitrage SaaS.

Security Considerations:
- All user data is scoped by user_id
- API keys are encrypted at rest using AES-256-GCM
- Passwords are hashed using Argon2id
- Audit logging for sensitive operations
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB

db = SQLAlchemy()


# ============== Enums ==============

class SubscriptionTier(Enum):
    """User subscription tiers."""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class ExchangeType(Enum):
    """Supported exchanges."""
    OKX = "okx"
    BINANCE = "binance"
    BYBIT = "bybit"


class ExchangeRole(Enum):
    """Exchange role in trading."""
    SPOT = "spot"
    FUTURES = "futures"
    BOTH = "both"


class BotStatus(Enum):
    """Trading bot status."""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


# ============== User Model ==============

class User(db.Model):
    """
    User account model.

    Stores authentication info and user-specific encryption salt.
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # User-specific salt for API key encryption
    # Each user has a unique salt so their keys are encrypted with a unique derived key
    encryption_salt = db.Column(db.LargeBinary(16), nullable=False)

    # Profile
    name = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_token = db.Column(db.String(255), nullable=True)

    # Subscription
    subscription_tier = db.Column(
        db.Enum(SubscriptionTier),
        default=SubscriptionTier.FREE,
        nullable=False
    )
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)

    # Bot status
    bot_status = db.Column(
        db.Enum(BotStatus),
        default=BotStatus.STOPPED,
        nullable=False
    )

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    exchanges = db.relationship('UserExchange', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    config = db.relationship('UserConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    trades = db.relationship('Trade', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        data = {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'subscription_tier': self.subscription_tier.value,
            'bot_status': self.bot_status.value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
        }
        return data

    # Flask-Login integration
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)


# ============== Exchange Credentials ==============

class UserExchange(db.Model):
    """
    User's exchange API credentials.

    CRITICAL: API keys and secrets are encrypted at rest using AES-256-GCM.
    The encryption key is derived from:
    - Application master key (from environment)
    - User-specific salt (stored in User model)

    NEVER log or expose decrypted credentials.
    """
    __tablename__ = 'user_exchanges'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Exchange info
    name = db.Column(db.String(100), nullable=False)  # User-friendly name
    exchange_type = db.Column(db.Enum(ExchangeType), nullable=False)
    role = db.Column(db.Enum(ExchangeRole), default=ExchangeRole.BOTH, nullable=False)

    # Encrypted credentials (AES-256-GCM, base64 encoded)
    encrypted_api_key = db.Column(db.Text, nullable=False)
    encrypted_secret_key = db.Column(db.Text, nullable=False)
    encrypted_passphrase = db.Column(db.Text, nullable=True)  # OKX only

    # Settings
    is_testnet = db.Column(db.Boolean, default=True, nullable=False)
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    # Status
    connection_status = db.Column(db.String(50), default='disconnected', nullable=False)
    last_error = db.Column(db.Text, nullable=True)
    last_connected_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        Index('idx_user_exchanges_user_active', 'user_id', 'is_active'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses. NEVER includes credentials."""
        return {
            'id': self.id,
            'name': self.name,
            'exchange_type': self.exchange_type.value,
            'role': self.role.value,
            'is_testnet': self.is_testnet,
            'is_active': self.is_active,
            'connection_status': self.connection_status,
            'last_error': self.last_error,
            'last_connected_at': self.last_connected_at.isoformat() if self.last_connected_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            # Indicate credentials exist but NEVER expose them
            'has_api_key': bool(self.encrypted_api_key),
            'has_passphrase': bool(self.encrypted_passphrase),
        }


# ============== Trading Configuration ==============

class UserConfig(db.Model):
    """
    User's trading configuration.

    Each user has one configuration record with all trading parameters.
    """
    __tablename__ = 'user_configs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)

    # Asset selection
    asset = db.Column(db.String(20), default='BTC', nullable=False)
    spot_symbol = db.Column(db.String(50), default='BTC-USDT', nullable=False)
    futures_symbol = db.Column(db.String(50), default='BTC-USDT-SWAP', nullable=False)

    # Z-score thresholds
    entry_threshold = db.Column(db.Float, default=2.0, nullable=False)
    exit_threshold = db.Column(db.Float, default=0.5, nullable=False)
    stop_loss_threshold = db.Column(db.Float, default=4.0, nullable=False)

    # Rolling window settings
    lookback_period = db.Column(db.Integer, default=100, nullable=False)
    stats_update_interval = db.Column(db.Integer, default=300, nullable=False)

    # Filters
    hurst_enabled = db.Column(db.Boolean, default=True, nullable=False)
    hurst_threshold = db.Column(db.Float, default=0.5, nullable=False)
    std_filter_enabled = db.Column(db.Boolean, default=True, nullable=False)
    min_std_multiple = db.Column(db.Float, default=1.5, nullable=False)

    # Position sizing
    position_size_usd = db.Column(db.Float, default=1000.0, nullable=False)
    max_position_size_usd = db.Column(db.Float, default=10000.0, nullable=False)

    # Trading mode
    paper_trading = db.Column(db.Boolean, default=True, nullable=False)
    algo_enabled = db.Column(db.Boolean, default=False, nullable=False)

    # Order execution
    order_execution_mode = db.Column(db.String(20), default='MARKET', nullable=False)
    limit_order_timeout_sec = db.Column(db.Integer, default=30, nullable=False)
    limit_order_price_offset_bps = db.Column(db.Float, default=1.0, nullable=False)

    # Fees
    taker_fee_bps = db.Column(db.Float, default=5.0, nullable=False)
    maker_fee_bps = db.Column(db.Float, default=2.0, nullable=False)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        CheckConstraint('entry_threshold > 0', name='check_entry_threshold_positive'),
        CheckConstraint('exit_threshold >= 0', name='check_exit_threshold_non_negative'),
        CheckConstraint('position_size_usd > 0', name='check_position_size_positive'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'asset': self.asset,
            'spot_symbol': self.spot_symbol,
            'futures_symbol': self.futures_symbol,
            'entry_threshold': self.entry_threshold,
            'exit_threshold': self.exit_threshold,
            'stop_loss_threshold': self.stop_loss_threshold,
            'lookback_period': self.lookback_period,
            'stats_update_interval': self.stats_update_interval,
            'hurst_enabled': self.hurst_enabled,
            'hurst_threshold': self.hurst_threshold,
            'std_filter_enabled': self.std_filter_enabled,
            'min_std_multiple': self.min_std_multiple,
            'position_size_usd': self.position_size_usd,
            'max_position_size_usd': self.max_position_size_usd,
            'paper_trading': self.paper_trading,
            'algo_enabled': self.algo_enabled,
            'order_execution_mode': self.order_execution_mode,
            'limit_order_timeout_sec': self.limit_order_timeout_sec,
            'limit_order_price_offset_bps': self.limit_order_price_offset_bps,
            'taker_fee_bps': self.taker_fee_bps,
            'maker_fee_bps': self.maker_fee_bps,
        }


# ============== Trade Records ==============

class Trade(db.Model):
    """
    Trade journal entries.

    Records all trades (paper and live) for analysis and reporting.
    """
    __tablename__ = 'trades'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Trade info
    asset = db.Column(db.String(20), nullable=False)
    position_type = db.Column(db.String(10), nullable=False)  # LONG or SHORT

    # Entry details
    entry_time = db.Column(db.DateTime(timezone=True), nullable=True)
    entry_spot_price = db.Column(db.Float, nullable=True)
    entry_futures_price = db.Column(db.Float, nullable=True)
    entry_spread = db.Column(db.Float, nullable=True)
    entry_zscore = db.Column(db.Float, nullable=True)

    # Exit details
    exit_time = db.Column(db.DateTime(timezone=True), nullable=True)
    exit_spot_price = db.Column(db.Float, nullable=True)
    exit_futures_price = db.Column(db.Float, nullable=True)
    exit_spread = db.Column(db.Float, nullable=True)
    exit_zscore = db.Column(db.Float, nullable=True)
    exit_reason = db.Column(db.String(50), nullable=True)

    # Position details
    quantity = db.Column(db.Float, nullable=False)
    notional_usd = db.Column(db.Float, nullable=False)

    # P&L
    pnl_usd = db.Column(db.Float, default=0.0, nullable=False)
    pnl_percent = db.Column(db.Float, default=0.0, nullable=False)

    # Order tracking
    spot_order_id = db.Column(db.String(100), nullable=True)
    futures_order_id = db.Column(db.String(100), nullable=True)

    # Status
    is_open = db.Column(db.Boolean, default=True, nullable=False)
    is_paper = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        Index('idx_trades_user_open', 'user_id', 'is_open'),
        Index('idx_trades_user_asset', 'user_id', 'asset'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'asset': self.asset,
            'position_type': self.position_type,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'entry_spot_price': self.entry_spot_price,
            'entry_futures_price': self.entry_futures_price,
            'entry_spread': self.entry_spread,
            'entry_zscore': self.entry_zscore,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'exit_spot_price': self.exit_spot_price,
            'exit_futures_price': self.exit_futures_price,
            'exit_spread': self.exit_spread,
            'exit_zscore': self.exit_zscore,
            'exit_reason': self.exit_reason,
            'quantity': self.quantity,
            'notional_usd': self.notional_usd,
            'pnl_usd': self.pnl_usd,
            'pnl_percent': self.pnl_percent,
            'is_open': self.is_open,
            'is_paper': self.is_paper,
        }


# ============== Analytics Tables ==============

class SDTouchEvent(db.Model):
    """Standard deviation touch events for analysis."""
    __tablename__ = 'sd_touch_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    asset = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sd_level = db.Column(db.Float, nullable=False)
    direction = db.Column(db.String(10), nullable=False)
    spread = db.Column(db.Float, nullable=False)
    zscore = db.Column(db.Float, nullable=False)
    spot_price = db.Column(db.Float, nullable=False)
    futures_price = db.Column(db.Float, nullable=False)

    __table_args__ = (
        Index('idx_sd_touch_user_asset', 'user_id', 'asset'),
    )


class SignalLog(db.Model):
    """Trading signal history."""
    __tablename__ = 'signal_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    asset = db.Column(db.String(20), nullable=False)
    signal_type = db.Column(db.String(20), nullable=False)
    zscore = db.Column(db.Float, nullable=False)
    spread = db.Column(db.Float, nullable=False)
    spread_mean = db.Column(db.Float, nullable=False)
    spread_std = db.Column(db.Float, nullable=False)
    hurst = db.Column(db.Float, nullable=True)
    regime = db.Column(db.String(20), nullable=True)

    __table_args__ = (
        Index('idx_signal_log_user_time', 'user_id', 'timestamp'),
    )


class SpreadHistory(db.Model):
    """Spread history for recovery after restart."""
    __tablename__ = 'spread_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    asset = db.Column(db.String(20), nullable=False)
    spot_price = db.Column(db.Float, nullable=False)
    futures_price = db.Column(db.Float, nullable=False)
    spread = db.Column(db.Float, nullable=False)

    __table_args__ = (
        Index('idx_spread_history_user_asset_time', 'user_id', 'asset', 'timestamp'),
    )


# ============== Subscription & Billing ==============

class Subscription(db.Model):
    """
    User subscription records.

    Tracks subscription history and Stripe integration.
    """
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Stripe IDs
    stripe_subscription_id = db.Column(db.String(255), nullable=True, unique=True)
    stripe_price_id = db.Column(db.String(255), nullable=True)

    # Subscription details
    tier = db.Column(db.Enum(SubscriptionTier), nullable=False)
    status = db.Column(db.String(50), nullable=False)  # active, canceled, past_due, etc.

    # Billing period
    current_period_start = db.Column(db.DateTime(timezone=True), nullable=True)
    current_period_end = db.Column(db.DateTime(timezone=True), nullable=True)

    # Trial
    trial_start = db.Column(db.DateTime(timezone=True), nullable=True)
    trial_end = db.Column(db.DateTime(timezone=True), nullable=True)

    # Cancellation
    cancel_at = db.Column(db.DateTime(timezone=True), nullable=True)
    canceled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'tier': self.tier.value,
            'status': self.status,
            'current_period_start': self.current_period_start.isoformat() if self.current_period_start else None,
            'current_period_end': self.current_period_end.isoformat() if self.current_period_end else None,
            'trial_end': self.trial_end.isoformat() if self.trial_end else None,
            'cancel_at': self.cancel_at.isoformat() if self.cancel_at else None,
        }


# ============== Audit Logging ==============

class AuditLog(db.Model):
    """
    Audit log for security-sensitive operations.

    Records:
    - Login attempts (success/failure)
    - API key additions/removals
    - Configuration changes
    - Trading actions
    """
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    # Event details
    event_type = db.Column(db.String(100), nullable=False)
    event_description = db.Column(db.Text, nullable=True)

    # Request context
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 compatible
    user_agent = db.Column(db.String(500), nullable=True)

    # Additional data (JSON)
    event_data = db.Column(JSONB, nullable=True)

    # Timestamp
    timestamp = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    __table_args__ = (
        Index('idx_audit_log_user_time', 'user_id', 'timestamp'),
        Index('idx_audit_log_event_type', 'event_type'),
    )
