"""
Authentication and authorization decorators.

Provides decorators for route protection:
- login_required: Requires authenticated user
- subscription_required: Requires specific subscription tier
- api_key_required: Requires valid API key (for external integrations)
"""

from functools import wraps
from typing import Callable, List, Optional

from flask import request, jsonify, g, current_app
from flask_login import current_user

from app.database.models import SubscriptionTier


def login_required(f: Callable) -> Callable:
    """
    Decorator to require authenticated user.

    Supports both session-based and JWT authentication.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check session-based auth first (Flask-Login)
        if current_user.is_authenticated:
            return f(*args, **kwargs)

        # Check for JWT in Authorization header
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]

            # Get JWT handler
            jwt_handler = current_app.extensions.get('jwt_handler')
            if jwt_handler:
                is_valid, payload, error = jwt_handler.verify_token(token)
                if is_valid:
                    # Load user and set in g
                    from app.database import User
                    user_id = int(payload['sub'])
                    user = User.query.get(user_id)
                    if user and user.is_active:
                        g.current_user = user
                        return f(*args, **kwargs)

                return jsonify({'error': error or 'Invalid token'}), 401

        return jsonify({'error': 'Authentication required'}), 401

    return decorated_function


def subscription_required(
    tiers: Optional[List[SubscriptionTier]] = None,
    min_tier: Optional[SubscriptionTier] = None,
) -> Callable:
    """
    Decorator to require specific subscription tier(s).

    Args:
        tiers: List of allowed tiers
        min_tier: Minimum required tier (inclusive)

    Usage:
        @subscription_required(tiers=[SubscriptionTier.PRO, SubscriptionTier.ENTERPRISE])
        def premium_feature():
            ...

        @subscription_required(min_tier=SubscriptionTier.PRO)
        def pro_feature():
            ...
    """
    # Tier hierarchy for min_tier checks
    tier_order = {
        SubscriptionTier.FREE: 0,
        SubscriptionTier.PRO: 1,
        SubscriptionTier.ENTERPRISE: 2,
    }

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            user = getattr(g, 'current_user', None) or current_user

            if not user or not user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401

            user_tier = user.subscription_tier

            # Check specific tiers
            if tiers and user_tier not in tiers:
                return jsonify({
                    'error': 'Subscription upgrade required',
                    'required_tiers': [t.value for t in tiers],
                    'current_tier': user_tier.value,
                }), 403

            # Check minimum tier
            if min_tier:
                if tier_order.get(user_tier, 0) < tier_order.get(min_tier, 0):
                    return jsonify({
                        'error': 'Subscription upgrade required',
                        'required_tier': min_tier.value,
                        'current_tier': user_tier.value,
                    }), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def api_key_required(f: Callable) -> Callable:
    """
    Decorator to require valid API key authentication.

    For external integrations where JWT/session isn't appropriate.
    API key should be passed in X-API-Key header.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key', '')

        if not api_key:
            return jsonify({'error': 'API key required'}), 401

        # Validate API key (implement lookup in database)
        # This is a placeholder - implement proper API key validation
        # user = validate_api_key(api_key)

        # For now, return unauthorized
        return jsonify({'error': 'Invalid API key'}), 401

        # If valid:
        # g.current_user = user
        # return f(*args, **kwargs)

    return decorated_function


def rate_limit(
    requests_per_minute: int = 60,
    requests_per_hour: int = 1000,
) -> Callable:
    """
    Decorator for rate limiting.

    Note: This is a basic implementation. In production,
    use flask-limiter with Redis backend.
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # In production, implement proper rate limiting with Redis
            # For now, just pass through
            return f(*args, **kwargs)

        return decorated_function

    return decorator
