"""
Subscription and billing API routes.

Handles subscription management and Stripe integration.
"""

from flask import request, jsonify, g, current_app, url_for
from flask_login import current_user

from . import subscription_bp, webhook_bp
from app.auth import login_required
from app.database import db, User, Subscription
from app.database.models import SubscriptionTier


@subscription_bp.route('/status', methods=['GET'])
@login_required
def get_subscription_status():
    """Get current subscription status."""
    user = getattr(g, 'current_user', None) or current_user

    from app.services import SubscriptionService
    sub_service = SubscriptionService()

    # Get active subscription
    subscription = Subscription.query.filter_by(
        user_id=user.id,
        status='active'
    ).first()

    limits = sub_service.get_tier_limits(user.subscription_tier)

    return jsonify({
        'tier': user.subscription_tier.value,
        'subscription': subscription.to_dict() if subscription else None,
        'limits': limits,
    })


@subscription_bp.route('/tiers', methods=['GET'])
def get_tiers():
    """Get available subscription tiers."""
    from app.services import SubscriptionService
    sub_service = SubscriptionService()

    tiers = []
    for tier in SubscriptionTier:
        limits = sub_service.get_tier_limits(tier)
        tiers.append({
            'id': tier.value,
            'name': tier.value.title(),
            'limits': limits,
        })

    return jsonify({'tiers': tiers})


@subscription_bp.route('/checkout', methods=['POST'])
@login_required
def create_checkout():
    """
    Create Stripe checkout session for subscription upgrade.

    Request body:
        tier: Target subscription tier (pro or enterprise)
    """
    user = getattr(g, 'current_user', None) or current_user
    data = request.get_json()

    if not data or 'tier' not in data:
        return jsonify({'error': 'tier required'}), 400

    try:
        tier = SubscriptionTier(data['tier'].lower())
    except ValueError:
        return jsonify({'error': f"Invalid tier: {data['tier']}"}), 400

    if tier == SubscriptionTier.FREE:
        return jsonify({'error': 'Cannot purchase free tier'}), 400

    from app.services import SubscriptionService
    sub_service = SubscriptionService()

    # Build URLs
    success_url = request.host_url.rstrip('/') + '/dashboard?subscription=success'
    cancel_url = request.host_url.rstrip('/') + '/settings/subscription?canceled=true'

    success, message, checkout_url = sub_service.create_checkout_session(
        user=user,
        tier=tier,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({
        'checkout_url': checkout_url,
    })


@subscription_bp.route('/cancel', methods=['POST'])
@login_required
def cancel_subscription():
    """Cancel current subscription (at end of billing period)."""
    user = getattr(g, 'current_user', None) or current_user

    if user.subscription_tier == SubscriptionTier.FREE:
        return jsonify({'error': 'No active subscription'}), 400

    from app.services import SubscriptionService
    sub_service = SubscriptionService()

    success, message = sub_service.cancel_subscription(user)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'message': message})


@subscription_bp.route('/portal', methods=['POST'])
@login_required
def create_portal_session():
    """
    Create Stripe customer portal session for managing billing.

    Returns URL to Stripe's hosted customer portal.
    """
    user = getattr(g, 'current_user', None) or current_user

    if not user.stripe_customer_id:
        return jsonify({'error': 'No billing account'}), 400

    try:
        import stripe

        return_url = request.host_url.rstrip('/') + '/settings/subscription'

        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )

        return jsonify({'portal_url': session.url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Stripe webhook handler
@webhook_bp.route('/stripe', methods=['POST'])
def stripe_webhook():
    """
    Handle Stripe webhook events.

    This endpoint receives events from Stripe for subscription changes,
    payment successes/failures, etc.
    """
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    from app.services import SubscriptionService
    sub_service = SubscriptionService()

    success, message = sub_service.handle_webhook(payload, sig_header)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'received': True})
