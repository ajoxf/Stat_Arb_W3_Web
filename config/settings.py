"""
Application configuration settings.

Loads configuration from environment variables with sensible defaults.
"""

import os
from datetime import timedelta


class Config:
    """Base configuration."""

    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')
    DEBUG = False
    TESTING = False

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/trading_saas'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Security
    MASTER_ENCRYPTION_KEY = os.getenv('MASTER_ENCRYPTION_KEY', 'change-me-32-chars-minimum-here!')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Session
    SESSION_TYPE = 'filesystem'
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_DEFAULT = '100/hour'
    RATELIMIT_STORAGE_URL = os.getenv('REDIS_URL', 'memory://')

    # Stripe
    STRIPE_API_KEY = os.getenv('STRIPE_API_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY', '')

    # Redis (for Celery and caching)
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # CORS
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    SESSION_COOKIE_SECURE = False

    # Use SQLite for local dev if no DATABASE_URL
    if not os.getenv('DATABASE_URL'):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///trading_dev.db'


class TestingConfig(Config):
    """Testing configuration."""

    TESTING = True
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    """Production configuration."""

    # Enforce secure cookies
    SESSION_COOKIE_SECURE = True

    # Stricter rate limits
    RATELIMIT_DEFAULT = '60/hour'

    # Require real encryption key
    @property
    def MASTER_ENCRYPTION_KEY(self):
        key = os.getenv('MASTER_ENCRYPTION_KEY')
        if not key or len(key) < 32:
            raise ValueError(
                "MASTER_ENCRYPTION_KEY must be set and at least 32 characters"
            )
        return key


# Config selector
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}


def get_config():
    """Get configuration based on environment."""
    env = os.getenv('FLASK_ENV', 'development')
    return config.get(env, config['default'])
