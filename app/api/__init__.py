"""
API routes for the SaaS trading platform.
"""

from flask import Blueprint

# Create blueprints
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
user_bp = Blueprint('user', __name__, url_prefix='/api/user')
trading_bp = Blueprint('trading', __name__, url_prefix='/api/trading')
exchange_bp = Blueprint('exchange', __name__, url_prefix='/api/exchanges')
subscription_bp = Blueprint('subscription', __name__, url_prefix='/api/subscription')
webhook_bp = Blueprint('webhook', __name__, url_prefix='/api/webhooks')

# Import routes to register them
from . import auth_routes
from . import user_routes
from . import trading_routes
from . import exchange_routes
from . import subscription_routes


def register_blueprints(app):
    """Register all API blueprints with the Flask app."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(trading_bp)
    app.register_blueprint(exchange_bp)
    app.register_blueprint(subscription_bp)
    app.register_blueprint(webhook_bp)
