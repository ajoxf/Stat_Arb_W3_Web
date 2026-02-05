#!/usr/bin/env python
"""
Application entry point.

Run with: python run.py
Or with gunicorn: gunicorn -k eventlet -w 1 run:app
"""

import os
import logging

from app import create_app, socketio

# Create application
app = create_app()

logger = logging.getLogger(__name__)


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'

    logger.info("=" * 50)
    logger.info("Starting Crypto Arbitrage SaaS")
    logger.info("Dashboard: http://localhost:%d", port)
    logger.info("=" * 50)

    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=debug,
    )
