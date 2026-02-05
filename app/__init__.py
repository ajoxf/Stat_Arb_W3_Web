"""
Crypto Statistical Arbitrage SaaS Application.

A multi-tenant trading platform for crypto spot-futures arbitrage.
"""

import os
import logging
import atexit

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from config.settings import get_config

# Initialize extensions
socketio = SocketIO()

logger = logging.getLogger(__name__)


def create_app(config_class=None):
    """
    Application factory.

    Creates and configures the Flask application.
    """
    app = Flask(__name__)

    # Load configuration
    if config_class is None:
        config_class = get_config()

    app.config.from_object(config_class)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, app.config.get('LOG_LEVEL', 'INFO')),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize extensions
    _init_extensions(app)

    # Register blueprints
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register shutdown handlers
    _register_shutdown_handlers(app)

    logger.info("Application initialized")

    return app


def _init_extensions(app):
    """Initialize Flask extensions."""
    from app.database import db
    from app.auth.service import login_manager
    from app.auth import JWTHandler
    from app.security import EncryptionService
    from app.services import ExchangeService, TradingOrchestrator, SubscriptionService

    # Database
    db.init_app(app)

    # CORS
    CORS(app, origins=app.config.get('CORS_ORIGINS', ['*']))

    # SocketIO
    socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet')

    # Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # JWT Handler
    jwt_handler = JWTHandler(
        secret_key=app.config['JWT_SECRET_KEY'],
    )
    app.extensions['jwt_handler'] = jwt_handler

    # Encryption Service
    encryption_service = EncryptionService(
        master_key=app.config['MASTER_ENCRYPTION_KEY']
    )
    app.extensions['encryption_service'] = encryption_service

    # Exchange Service
    exchange_service = ExchangeService(encryption_service)
    app.extensions['exchange_service'] = exchange_service

    # Trading Orchestrator
    trading_orchestrator = TradingOrchestrator(exchange_service)
    app.extensions['trading_orchestrator'] = trading_orchestrator

    # Subscription Service (Stripe)
    if app.config.get('STRIPE_API_KEY'):
        import stripe
        stripe.api_key = app.config['STRIPE_API_KEY']
        subscription_service = SubscriptionService(app.config['STRIPE_API_KEY'])
        app.extensions['subscription_service'] = subscription_service

    # Create database tables
    with app.app_context():
        db.create_all()

    logger.info("Extensions initialized")


def _register_blueprints(app):
    """Register Flask blueprints."""
    from flask import render_template, redirect, url_for
    from flask_login import login_required, current_user
    from app.api import register_blueprints

    # API routes
    register_blueprints(app)

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'healthy'}

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('login'))

    # View routes (HTML pages)
    @app.route('/login')
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return render_template('login.html')

    @app.route('/register')
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return render_template('login.html')

    @app.route('/dashboard')
    @login_required
    def dashboard():
        return render_template('dashboard.html')

    logger.info("Blueprints registered")


def _register_error_handlers(app):
    """Register error handlers."""
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({'error': 'Bad request'}), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({'error': 'Unauthorized'}), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({'error': 'Forbidden'}), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.exception("Internal server error")
        return jsonify({'error': 'Internal server error'}), 500


def _register_shutdown_handlers(app):
    """Register shutdown handlers for graceful cleanup."""

    def shutdown():
        logger.info("Shutting down...")

        # Stop all trading engines
        orchestrator = app.extensions.get('trading_orchestrator')
        if orchestrator:
            orchestrator.stop_all()

        logger.info("Shutdown complete")

    atexit.register(shutdown)
