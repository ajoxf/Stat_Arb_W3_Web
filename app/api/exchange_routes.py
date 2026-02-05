"""
Exchange management API routes.

Handles adding, updating, and removing exchange API credentials.
"""

from flask import request, jsonify, g, current_app
from flask_login import current_user

from . import exchange_bp
from app.auth import login_required
from app.database import db, User, UserExchange
from app.database.models import ExchangeType, ExchangeRole


@exchange_bp.route('', methods=['GET'])
@login_required
def list_exchanges():
    """Get all exchanges for current user."""
    user = getattr(g, 'current_user', None) or current_user

    exchanges = UserExchange.query.filter_by(user_id=user.id).all()

    return jsonify({
        'exchanges': [e.to_dict() for e in exchanges],
    })


@exchange_bp.route('', methods=['POST'])
@login_required
def add_exchange():
    """
    Add a new exchange.

    Request body:
        name: Friendly name
        exchange_type: okx, binance, or bybit
        api_key: API key
        secret_key: Secret key
        passphrase: Passphrase (OKX only)
        is_testnet: Whether this is testnet/demo
        role: spot, futures, or both
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    # Validate required fields
    required = ['name', 'exchange_type', 'api_key', 'secret_key']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    # Validate exchange type
    try:
        exchange_type = ExchangeType(data['exchange_type'].lower())
    except ValueError:
        return jsonify({'error': f"Invalid exchange type: {data['exchange_type']}"}), 400

    # Validate role
    role = ExchangeRole.BOTH
    if 'role' in data:
        try:
            role = ExchangeRole(data['role'].lower())
        except ValueError:
            return jsonify({'error': f"Invalid role: {data['role']}"}), 400

    # Check subscription limits
    from app.services import SubscriptionService
    sub_service = SubscriptionService()
    limits = sub_service.get_tier_limits(user.subscription_tier)
    current_count = UserExchange.query.filter_by(user_id=user.id).count()

    if current_count >= limits.get('max_exchanges', 1):
        return jsonify({
            'error': f"Exchange limit reached ({limits['max_exchanges']}). Upgrade to add more.",
            'upgrade_required': True,
        }), 403

    # Get exchange service
    exchange_service = current_app.extensions.get('exchange_service')
    if not exchange_service:
        return jsonify({'error': 'Exchange service not available'}), 503

    # Add exchange
    success, message, exchange = exchange_service.add_exchange(
        user=user,
        name=data['name'],
        exchange_type=exchange_type,
        api_key=data['api_key'],
        secret_key=data['secret_key'],
        passphrase=data.get('passphrase'),
        is_testnet=data.get('is_testnet', True),
        role=role,
    )

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({
        'message': message,
        'exchange': exchange.to_dict(),
    }), 201


@exchange_bp.route('/<int:exchange_id>', methods=['GET'])
@login_required
def get_exchange(exchange_id):
    """Get a specific exchange."""
    user = getattr(g, 'current_user', None) or current_user

    exchange = UserExchange.query.filter_by(
        id=exchange_id,
        user_id=user.id
    ).first()

    if not exchange:
        return jsonify({'error': 'Exchange not found'}), 404

    return jsonify({'exchange': exchange.to_dict()})


@exchange_bp.route('/<int:exchange_id>', methods=['PUT'])
@login_required
def update_exchange(exchange_id):
    """
    Update exchange settings or credentials.

    Request body can include any of:
        name: New name
        api_key: New API key
        secret_key: New secret key
        passphrase: New passphrase
        is_testnet: Update testnet setting
        role: Update role
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    exchange = UserExchange.query.filter_by(
        id=exchange_id,
        user_id=user.id
    ).first()

    if not exchange:
        return jsonify({'error': 'Exchange not found'}), 404

    exchange_service = current_app.extensions.get('exchange_service')
    if not exchange_service:
        return jsonify({'error': 'Exchange service not available'}), 503

    # Parse role if provided
    role = None
    if 'role' in data:
        try:
            role = ExchangeRole(data['role'].lower())
        except ValueError:
            return jsonify({'error': f"Invalid role: {data['role']}"}), 400

    success, message = exchange_service.update_exchange(
        user=user,
        exchange_id=exchange_id,
        name=data.get('name'),
        api_key=data.get('api_key'),
        secret_key=data.get('secret_key'),
        passphrase=data.get('passphrase'),
        is_testnet=data.get('is_testnet'),
        role=role,
    )

    if not success:
        return jsonify({'error': message}), 400

    # Refresh exchange from DB
    exchange = UserExchange.query.get(exchange_id)

    return jsonify({
        'message': message,
        'exchange': exchange.to_dict(),
    })


@exchange_bp.route('/<int:exchange_id>', methods=['DELETE'])
@login_required
def delete_exchange(exchange_id):
    """Delete an exchange."""
    user = getattr(g, 'current_user', None) or current_user

    exchange_service = current_app.extensions.get('exchange_service')
    if not exchange_service:
        return jsonify({'error': 'Exchange service not available'}), 503

    success, message = exchange_service.delete_exchange(user, exchange_id)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'message': message})


@exchange_bp.route('/<int:exchange_id>/test', methods=['POST'])
@login_required
def test_exchange(exchange_id):
    """
    Test exchange connection.

    Attempts to connect and fetch account info.
    """
    user = getattr(g, 'current_user', None) or current_user

    exchange = UserExchange.query.filter_by(
        id=exchange_id,
        user_id=user.id
    ).first()

    if not exchange:
        return jsonify({'error': 'Exchange not found'}), 404

    exchange_service = current_app.extensions.get('exchange_service')
    if not exchange_service:
        return jsonify({'error': 'Exchange service not available'}), 503

    # Get decrypted credentials
    credentials = exchange_service.get_decrypted_credentials(user, exchange)
    if not credentials:
        return jsonify({'error': 'Failed to decrypt credentials'}), 500

    # Create adapter and test connection
    try:
        from app.adapters import OKXAdapter, BinanceAdapter, BybitAdapter

        if exchange.exchange_type == ExchangeType.OKX:
            adapter = OKXAdapter(
                api_key=credentials['api_key'],
                secret_key=credentials['secret_key'],
                passphrase=credentials.get('passphrase', ''),
                is_testnet=exchange.is_testnet,
            )
        elif exchange.exchange_type == ExchangeType.BINANCE:
            adapter = BinanceAdapter(
                api_key=credentials['api_key'],
                secret_key=credentials['secret_key'],
                is_testnet=exchange.is_testnet,
            )
        elif exchange.exchange_type == ExchangeType.BYBIT:
            adapter = BybitAdapter(
                api_key=credentials['api_key'],
                secret_key=credentials['secret_key'],
                is_testnet=exchange.is_testnet,
            )
        else:
            return jsonify({'error': 'Unknown exchange type'}), 400

        # Test connection
        import asyncio

        async def test_connection():
            connected = await adapter.connect()
            if connected:
                account = await adapter.get_account_info()
                await adapter.disconnect()
                return True, account.to_dict() if account else {}
            else:
                return False, adapter.last_error

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            success, result = loop.run_until_complete(test_connection())
        finally:
            loop.close()

        # Update status
        exchange_service.update_connection_status(
            exchange,
            'connected' if success else 'error',
            None if success else str(result)
        )

        if success:
            return jsonify({
                'success': True,
                'account': result,
            })
        else:
            return jsonify({
                'success': False,
                'error': str(result),
            }), 400

    except Exception as e:
        exchange_service.update_connection_status(exchange, 'error', str(e))
        return jsonify({
            'success': False,
            'error': str(e),
        }), 500


@exchange_bp.route('/<int:exchange_id>/activate', methods=['POST'])
@login_required
def activate_exchange(exchange_id):
    """
    Activate an exchange for trading.

    Request body:
        active: boolean
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if data is None or 'active' not in data:
        return jsonify({'error': 'active field required'}), 400

    is_active = bool(data['active'])

    exchange_service = current_app.extensions.get('exchange_service')
    if not exchange_service:
        return jsonify({'error': 'Exchange service not available'}), 503

    success, message = exchange_service.set_active_exchange(
        user, exchange_id, is_active
    )

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'message': message})


@exchange_bp.route('/types', methods=['GET'])
@login_required
def get_exchange_types():
    """Get supported exchange types."""
    return jsonify({
        'types': [
            {'id': 'okx', 'name': 'OKX', 'requires_passphrase': True},
            {'id': 'binance', 'name': 'Binance', 'requires_passphrase': False},
            {'id': 'bybit', 'name': 'Bybit', 'requires_passphrase': False},
        ],
        'roles': [
            {'id': 'spot', 'name': 'Spot Only'},
            {'id': 'futures', 'name': 'Futures Only'},
            {'id': 'both', 'name': 'Both'},
        ],
    })
