"""
Trading API routes.

Handles trading engine control, status, and real-time updates.
"""

from flask import request, jsonify, g, current_app
from flask_login import current_user

from . import trading_bp
from app.auth import login_required, subscription_required
from app.database import db, User
from app.database.models import SubscriptionTier, BotStatus


@trading_bp.route('/status', methods=['GET'])
@login_required
def get_status():
    """Get trading engine status."""
    user = getattr(g, 'current_user', None) or current_user

    orchestrator = current_app.extensions.get('trading_orchestrator')
    if not orchestrator:
        return jsonify({'error': 'Trading service not available'}), 503

    status = orchestrator.get_status(user)
    return jsonify(status)


@trading_bp.route('/start', methods=['POST'])
@login_required
def start_trading():
    """
    Start the trading engine.

    Requires active exchange connections and valid configuration.
    """
    user = getattr(g, 'current_user', None) or current_user

    orchestrator = current_app.extensions.get('trading_orchestrator')
    if not orchestrator:
        return jsonify({'error': 'Trading service not available'}), 503

    # Check subscription for live trading
    if not user.config or not user.config.paper_trading:
        if user.subscription_tier == SubscriptionTier.FREE:
            return jsonify({
                'error': 'Live trading requires a Pro subscription',
                'upgrade_required': True,
            }), 403

    success, message = orchestrator.start_trading(user)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({
        'message': message,
        'status': orchestrator.get_status(user),
    })


@trading_bp.route('/stop', methods=['POST'])
@login_required
def stop_trading():
    """Stop the trading engine."""
    user = getattr(g, 'current_user', None) or current_user

    orchestrator = current_app.extensions.get('trading_orchestrator')
    if not orchestrator:
        return jsonify({'error': 'Trading service not available'}), 503

    success, message = orchestrator.stop_trading(user)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({
        'message': message,
        'status': orchestrator.get_status(user),
    })


@trading_bp.route('/toggle-algo', methods=['POST'])
@login_required
def toggle_algo():
    """
    Toggle algorithmic trading on/off.

    Request body:
        enabled: boolean
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if data is None or 'enabled' not in data:
        return jsonify({'error': 'enabled field required'}), 400

    enabled = bool(data['enabled'])

    # Update config
    if user.config:
        user.config.algo_enabled = enabled
        db.session.commit()

    # Update running engine
    orchestrator = current_app.extensions.get('trading_orchestrator')
    if orchestrator:
        orchestrator.toggle_algo(user, enabled)

    return jsonify({
        'message': f"Algo trading {'enabled' if enabled else 'disabled'}",
        'algo_enabled': enabled,
    })


@trading_bp.route('/spread-history', methods=['GET'])
@login_required
def get_spread_history():
    """Get spread and Z-score history for charting."""
    user = getattr(g, 'current_user', None) or current_user

    n = request.args.get('n', 100, type=int)

    orchestrator = current_app.extensions.get('trading_orchestrator')
    if not orchestrator:
        return jsonify({'spreads': [], 'zscores': []})

    status = orchestrator.get_status(user)

    if not status.get('is_running'):
        # Return from database if not running
        from app.database import SpreadHistory
        spreads = SpreadHistory.query.filter_by(
            user_id=user.id,
            asset=user.config.asset if user.config else 'BTC'
        ).order_by(
            SpreadHistory.timestamp.desc()
        ).limit(n).all()

        spread_values = [s.spread for s in reversed(spreads)]
        return jsonify({
            'spreads': spread_values,
            'zscores': [],
        })

    # Get from running engine
    # This requires accessing the engine which is in the orchestrator
    return jsonify({
        'spreads': status.get('signal', {}).get('spread_history', []),
        'zscores': status.get('signal', {}).get('zscore_history', []),
    })


@trading_bp.route('/reset', methods=['POST'])
@login_required
def reset_engine():
    """
    Reset trading engine state.

    This clears spread history, resets position, but keeps config.
    """
    user = getattr(g, 'current_user', None) or current_user

    # Clear spread history
    from app.database import SpreadHistory, SDTouchEvent, SignalLog

    if user.config:
        SpreadHistory.query.filter_by(
            user_id=user.id,
            asset=user.config.asset
        ).delete()

        SDTouchEvent.query.filter_by(
            user_id=user.id,
            asset=user.config.asset
        ).delete()

        SignalLog.query.filter_by(
            user_id=user.id,
            asset=user.config.asset
        ).delete()

    db.session.commit()

    return jsonify({'message': 'Engine state reset'})


@trading_bp.route('/close-position', methods=['POST'])
@login_required
def close_position():
    """
    Manually close the current open position.

    This creates a market order to exit immediately.
    """
    user = getattr(g, 'current_user', None) or current_user

    orchestrator = current_app.extensions.get('trading_orchestrator')
    if not orchestrator:
        return jsonify({'error': 'Trading service not available'}), 503

    status = orchestrator.get_status(user)

    if not status.get('is_running'):
        return jsonify({'error': 'Trading engine not running'}), 400

    if status.get('position') == 'NONE':
        return jsonify({'error': 'No open position'}), 400

    # TODO: Implement manual position close in orchestrator
    return jsonify({'error': 'Manual close not yet implemented'}), 501


@trading_bp.route('/paper-mode', methods=['POST'])
@login_required
def set_paper_mode():
    """
    Set paper trading mode.

    Request body:
        enabled: boolean
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if data is None or 'enabled' not in data:
        return jsonify({'error': 'enabled field required'}), 400

    enabled = bool(data['enabled'])

    # Check subscription for live trading
    if not enabled and user.subscription_tier == SubscriptionTier.FREE:
        return jsonify({
            'error': 'Live trading requires a Pro subscription',
            'upgrade_required': True,
        }), 403

    if user.config:
        user.config.paper_trading = enabled
        db.session.commit()

    return jsonify({
        'message': f"Paper trading {'enabled' if enabled else 'disabled'}",
        'paper_trading': enabled,
    })
