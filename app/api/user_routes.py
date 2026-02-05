"""
User management API routes.

Handles user profile, settings, and preferences.
"""

from flask import request, jsonify, g
from flask_login import current_user

from . import user_bp
from app.auth import login_required
from app.database import db, User, UserConfig
from app.core.models import CRYPTO_ASSETS


@user_bp.route('/profile', methods=['GET'])
@login_required
def get_profile():
    """Get user profile."""
    user = getattr(g, 'current_user', None) or current_user
    return jsonify({
        'user': user.to_dict(),
        'config': user.config.to_dict() if user.config else None,
    })


@user_bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    """
    Update user profile.

    Request body:
        name: Display name
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    if 'name' in data:
        user.name = data['name'].strip() or None

    db.session.commit()

    return jsonify({
        'message': 'Profile updated',
        'user': user.to_dict(),
    })


@user_bp.route('/config', methods=['GET'])
@login_required
def get_config():
    """Get user's trading configuration."""
    user = getattr(g, 'current_user', None) or current_user

    if not user.config:
        # Create default config
        config = UserConfig(user_id=user.id)
        db.session.add(config)
        db.session.commit()

    return jsonify({
        'config': user.config.to_dict(),
        'assets': list(CRYPTO_ASSETS.keys()),
    })


@user_bp.route('/config', methods=['PUT'])
@login_required
def update_config():
    """
    Update user's trading configuration.

    Request body:
        Any config fields to update
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    if not user.config:
        config = UserConfig(user_id=user.id)
        db.session.add(config)
    else:
        config = user.config

    # Update allowed fields
    allowed_fields = [
        'asset', 'spot_symbol', 'futures_symbol',
        'entry_threshold', 'exit_threshold', 'stop_loss_threshold',
        'lookback_period', 'stats_update_interval',
        'hurst_enabled', 'hurst_threshold',
        'std_filter_enabled', 'min_std_multiple',
        'position_size_usd', 'max_position_size_usd',
        'paper_trading', 'algo_enabled',
        'order_execution_mode', 'limit_order_timeout_sec',
        'limit_order_price_offset_bps',
        'taker_fee_bps', 'maker_fee_bps',
    ]

    for field in allowed_fields:
        if field in data:
            setattr(config, field, data[field])

    # Validate asset
    if config.asset not in CRYPTO_ASSETS:
        return jsonify({'error': f'Invalid asset: {config.asset}'}), 400

    # Update symbols if asset changed
    if 'asset' in data and data['asset'] in CRYPTO_ASSETS:
        asset_config = CRYPTO_ASSETS[data['asset']]
        config.spot_symbol = asset_config.get('okx_spot', config.spot_symbol)
        config.futures_symbol = asset_config.get('okx_futures', config.futures_symbol)

    db.session.commit()

    # Update running engine if any
    from flask import current_app
    orchestrator = current_app.extensions.get('trading_orchestrator')
    if orchestrator:
        orchestrator.update_config(user, config)

    return jsonify({
        'message': 'Configuration updated',
        'config': config.to_dict(),
    })


@user_bp.route('/statistics', methods=['GET'])
@login_required
def get_statistics():
    """Get user's trading statistics."""
    user = getattr(g, 'current_user', None) or current_user

    from app.database import Trade

    # Get completed trades
    trades = Trade.query.filter_by(
        user_id=user.id,
        is_open=False
    ).all()

    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.pnl_usd > 0)
    losing_trades = total_trades - winning_trades
    total_pnl = sum(t.pnl_usd for t in trades)
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    # Calculate max drawdown and other metrics
    cumulative_pnl = 0
    max_cumulative = 0
    max_drawdown = 0

    for trade in sorted(trades, key=lambda t: t.exit_time or t.entry_time):
        cumulative_pnl += trade.pnl_usd
        max_cumulative = max(max_cumulative, cumulative_pnl)
        drawdown = max_cumulative - cumulative_pnl
        max_drawdown = max(max_drawdown, drawdown)

    return jsonify({
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': round(win_rate, 2),
        'total_pnl': round(total_pnl, 2),
        'avg_pnl': round(avg_pnl, 2),
        'max_drawdown': round(max_drawdown, 2),
    })


@user_bp.route('/trades', methods=['GET'])
@login_required
def get_trades():
    """Get user's trade history."""
    user = getattr(g, 'current_user', None) or current_user

    from app.database import Trade

    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    open_only = request.args.get('open_only', 'false').lower() == 'true'

    query = Trade.query.filter_by(user_id=user.id)

    if open_only:
        query = query.filter_by(is_open=True)

    trades = query.order_by(
        Trade.entry_time.desc()
    ).offset(offset).limit(limit).all()

    return jsonify({
        'trades': [t.to_dict() for t in trades],
        'count': len(trades),
    })


@user_bp.route('/trades/<int:trade_id>', methods=['DELETE'])
@login_required
def delete_trade(trade_id):
    """Delete a trade from history."""
    user = getattr(g, 'current_user', None) or current_user

    from app.database import Trade

    trade = Trade.query.filter_by(
        id=trade_id,
        user_id=user.id
    ).first()

    if not trade:
        return jsonify({'error': 'Trade not found'}), 404

    db.session.delete(trade)
    db.session.commit()

    return jsonify({'message': 'Trade deleted'})


@user_bp.route('/assets', methods=['GET'])
@login_required
def get_assets():
    """Get available trading assets."""
    return jsonify({
        'assets': CRYPTO_ASSETS,
    })
