"""
Authentication API routes.

Handles user registration, login, logout, and token management.
"""

from flask import request, jsonify, current_app, g
from flask_login import current_user, login_required as flask_login_required

from . import auth_bp
from app.auth import AuthService, JWTHandler
from app.database import db, User, AuditLog


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Register a new user.

    Request body:
        email: User email
        password: User password
        name: Optional display name

    Returns:
        User object and JWT tokens on success
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = data.get('email', '').strip()
    password = data.get('password', '')
    name = data.get('name', '').strip() or None

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    auth_service = AuthService()
    success, message, user = auth_service.register_user(email, password, name)

    if not success:
        return jsonify({'error': message}), 400

    # Generate tokens
    jwt_handler = current_app.extensions.get('jwt_handler')
    tokens = jwt_handler.create_token_pair(user.id)

    return jsonify({
        'message': message,
        'user': user.to_dict(),
        **tokens,
    }), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticate user and return tokens.

    Request body:
        email: User email
        password: User password
        remember: Optional boolean for session persistence

    Returns:
        User object and JWT tokens on success
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = data.get('email', '').strip()
    password = data.get('password', '')
    remember = data.get('remember', False)

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    auth_service = AuthService()
    success, message, user = auth_service.login(email, password, remember)

    if not success:
        return jsonify({'error': message}), 401

    # Generate tokens
    jwt_handler = current_app.extensions.get('jwt_handler')
    tokens = jwt_handler.create_token_pair(user.id)

    return jsonify({
        'message': message,
        'user': user.to_dict(),
        **tokens,
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Log out current user.

    Revokes the current JWT token if provided.
    """
    auth_service = AuthService()
    auth_service.logout()

    # Revoke JWT if provided
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        jwt_handler = current_app.extensions.get('jwt_handler')
        if jwt_handler:
            jwt_handler.revoke_token(token)

    return jsonify({'message': 'Logged out successfully'})


@auth_bp.route('/refresh', methods=['POST'])
def refresh_token():
    """
    Refresh access token using refresh token.

    Request body:
        refresh_token: The refresh token

    Returns:
        New access and refresh tokens
    """
    data = request.get_json()

    if not data or 'refresh_token' not in data:
        return jsonify({'error': 'Refresh token required'}), 400

    jwt_handler = current_app.extensions.get('jwt_handler')
    success, tokens, error = jwt_handler.refresh_access_token(data['refresh_token'])

    if not success:
        return jsonify({'error': error}), 401

    return jsonify(tokens)


@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """
    Get current authenticated user.

    Requires authentication via session or JWT.
    """
    # Check session auth
    if current_user.is_authenticated:
        return jsonify({'user': current_user.to_dict()})

    # Check JWT auth
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        jwt_handler = current_app.extensions.get('jwt_handler')
        if jwt_handler:
            is_valid, payload, error = jwt_handler.verify_token(token)
            if is_valid:
                user = User.query.get(int(payload['sub']))
                if user:
                    return jsonify({'user': user.to_dict()})
                return jsonify({'error': 'User not found'}), 404
            return jsonify({'error': error}), 401

    return jsonify({'error': 'Not authenticated'}), 401


@auth_bp.route('/change-password', methods=['POST'])
@flask_login_required
def change_password():
    """
    Change user password.

    Request body:
        current_password: Current password
        new_password: New password
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return jsonify({'error': 'Both passwords required'}), 400

    auth_service = AuthService()
    success, message = auth_service.change_password(
        current_user, current_password, new_password
    )

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'message': message})


@auth_bp.route('/verify-email/<token>', methods=['GET'])
def verify_email(token):
    """
    Verify user's email address.

    Args:
        token: Verification token from email
    """
    auth_service = AuthService()
    success, message = auth_service.verify_email(token)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'message': message})


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """
    Initiate password reset.

    Request body:
        email: User email
    """
    data = request.get_json()

    if not data or 'email' not in data:
        return jsonify({'error': 'Email required'}), 400

    auth_service = AuthService()
    success, message, _ = auth_service.initiate_password_reset(data['email'])

    # Always return success to prevent email enumeration
    return jsonify({'message': message})
