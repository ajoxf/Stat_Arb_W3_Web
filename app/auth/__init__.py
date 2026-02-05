"""
Authentication module with Flask-Login and JWT support.
"""

from .service import AuthService
from .decorators import login_required, subscription_required, api_key_required
from .jwt_handler import JWTHandler

__all__ = [
    'AuthService',
    'login_required',
    'subscription_required',
    'api_key_required',
    'JWTHandler',
]
