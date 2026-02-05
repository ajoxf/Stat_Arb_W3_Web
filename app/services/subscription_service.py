"""
Subscription management service with Stripe integration.

Handles:
- Subscription creation and management
- Stripe webhook processing
- Tier limits enforcement
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

import stripe
from flask import current_app

from app.database import db, User, Subscription
from app.database.models import SubscriptionTier

logger = logging.getLogger(__name__)


class SubscriptionService:
    """
    Service for managing user subscriptions with Stripe.

    Subscription Tiers:
    - FREE: Basic features, paper trading only
    - PRO: Live trading, all features
    - ENTERPRISE: Multiple bots, priority support
    """

    # Tier limits
    TIER_LIMITS = {
        SubscriptionTier.FREE: {
            'max_exchanges': 1,
            'max_position_size': 1000,
            'paper_trading_only': True,
            'priority_support': False,
        },
        SubscriptionTier.PRO: {
            'max_exchanges': 3,
            'max_position_size': 50000,
            'paper_trading_only': False,
            'priority_support': False,
        },
        SubscriptionTier.ENTERPRISE: {
            'max_exchanges': 10,
            'max_position_size': 500000,
            'paper_trading_only': False,
            'priority_support': True,
        },
    }

    # Stripe price IDs (configure in environment)
    PRICE_IDS = {
        SubscriptionTier.PRO: 'price_pro_monthly',  # Replace with actual Stripe price ID
        SubscriptionTier.ENTERPRISE: 'price_enterprise_monthly',
    }

    def __init__(self, stripe_api_key: Optional[str] = None):
        """
        Initialize subscription service.

        Args:
            stripe_api_key: Stripe API key (optional, uses config if not provided)
        """
        if stripe_api_key:
            stripe.api_key = stripe_api_key

    def get_tier_limits(self, tier: SubscriptionTier) -> Dict[str, Any]:
        """Get limits for a subscription tier."""
        return self.TIER_LIMITS.get(tier, self.TIER_LIMITS[SubscriptionTier.FREE])

    def check_tier_limit(
        self,
        user: User,
        limit_name: str,
        value: Any = None,
    ) -> Tuple[bool, str]:
        """
        Check if user is within their tier limits.

        Args:
            user: The user
            limit_name: Name of the limit to check
            value: Value to check against limit (for numeric limits)

        Returns:
            Tuple of (is_allowed, message)
        """
        limits = self.get_tier_limits(user.subscription_tier)

        if limit_name not in limits:
            return True, ""

        limit_value = limits[limit_name]

        # Boolean limits
        if isinstance(limit_value, bool):
            if limit_value:
                return False, f"This feature is restricted for {user.subscription_tier.value} tier"
            return True, ""

        # Numeric limits
        if value is not None and isinstance(limit_value, (int, float)):
            if value > limit_value:
                return False, f"Limit exceeded: max {limit_name} is {limit_value}"

        return True, ""

    def create_checkout_session(
        self,
        user: User,
        tier: SubscriptionTier,
        success_url: str,
        cancel_url: str,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Create a Stripe checkout session for subscription.

        Args:
            user: The user
            tier: Target subscription tier
            success_url: URL to redirect on success
            cancel_url: URL to redirect on cancel

        Returns:
            Tuple of (success, message, checkout_url)
        """
        if tier == SubscriptionTier.FREE:
            return False, "Cannot purchase free tier", None

        price_id = self.PRICE_IDS.get(tier)
        if not price_id:
            return False, f"No pricing configured for {tier.value}", None

        try:
            # Get or create Stripe customer
            if not user.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=user.email,
                    name=user.name,
                    metadata={'user_id': str(user.id)},
                )
                user.stripe_customer_id = customer.id
                db.session.commit()

            # Create checkout session
            session = stripe.checkout.Session.create(
                customer=user.stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'user_id': str(user.id),
                    'tier': tier.value,
                },
            )

            return True, "Checkout session created", session.url

        except stripe.error.StripeError as e:
            logger.error("Stripe error: %s", str(e))
            return False, f"Payment error: {str(e)}", None
        except Exception as e:
            logger.error("Checkout error: %s", str(e))
            return False, "Failed to create checkout session", None

    def handle_webhook(self, payload: bytes, sig_header: str) -> Tuple[bool, str]:
        """
        Handle Stripe webhook events.

        Args:
            payload: Raw webhook payload
            sig_header: Stripe signature header

        Returns:
            Tuple of (success, message)
        """
        webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except ValueError:
            return False, "Invalid payload"
        except stripe.error.SignatureVerificationError:
            return False, "Invalid signature"

        # Handle specific events
        event_type = event['type']
        data = event['data']['object']

        handlers = {
            'checkout.session.completed': self._handle_checkout_completed,
            'customer.subscription.updated': self._handle_subscription_updated,
            'customer.subscription.deleted': self._handle_subscription_deleted,
            'invoice.payment_failed': self._handle_payment_failed,
        }

        handler = handlers.get(event_type)
        if handler:
            return handler(data)

        return True, f"Unhandled event: {event_type}"

    def _handle_checkout_completed(self, data: Dict) -> Tuple[bool, str]:
        """Handle successful checkout."""
        user_id = data.get('metadata', {}).get('user_id')
        tier = data.get('metadata', {}).get('tier')
        subscription_id = data.get('subscription')

        if not user_id or not tier or not subscription_id:
            return False, "Missing metadata"

        try:
            user = User.query.get(int(user_id))
            if not user:
                return False, "User not found"

            # Update user subscription
            user.subscription_tier = SubscriptionTier(tier)
            user.stripe_subscription_id = subscription_id

            # Create subscription record
            subscription = Subscription(
                user_id=user.id,
                stripe_subscription_id=subscription_id,
                tier=SubscriptionTier(tier),
                status='active',
            )
            db.session.add(subscription)
            db.session.commit()

            logger.info("Subscription created: user_id=%d, tier=%s", user.id, tier)
            return True, "Subscription activated"

        except Exception as e:
            logger.error("Error handling checkout: %s", str(e))
            db.session.rollback()
            return False, str(e)

    def _handle_subscription_updated(self, data: Dict) -> Tuple[bool, str]:
        """Handle subscription update."""
        subscription_id = data.get('id')
        status = data.get('status')

        subscription = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()

        if not subscription:
            return False, "Subscription not found"

        try:
            subscription.status = status
            subscription.current_period_start = datetime.fromtimestamp(
                data.get('current_period_start', 0), tz=timezone.utc
            )
            subscription.current_period_end = datetime.fromtimestamp(
                data.get('current_period_end', 0), tz=timezone.utc
            )

            if data.get('cancel_at'):
                subscription.cancel_at = datetime.fromtimestamp(
                    data['cancel_at'], tz=timezone.utc
                )

            db.session.commit()

            logger.info("Subscription updated: %s, status=%s", subscription_id, status)
            return True, "Subscription updated"

        except Exception as e:
            logger.error("Error updating subscription: %s", str(e))
            db.session.rollback()
            return False, str(e)

    def _handle_subscription_deleted(self, data: Dict) -> Tuple[bool, str]:
        """Handle subscription cancellation."""
        subscription_id = data.get('id')

        subscription = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()

        if not subscription:
            return False, "Subscription not found"

        try:
            subscription.status = 'canceled'
            subscription.canceled_at = datetime.now(timezone.utc)

            # Downgrade user to free tier
            user = User.query.get(subscription.user_id)
            if user:
                user.subscription_tier = SubscriptionTier.FREE
                user.stripe_subscription_id = None

            db.session.commit()

            logger.info("Subscription canceled: user_id=%d", subscription.user_id)
            return True, "Subscription canceled"

        except Exception as e:
            logger.error("Error canceling subscription: %s", str(e))
            db.session.rollback()
            return False, str(e)

    def _handle_payment_failed(self, data: Dict) -> Tuple[bool, str]:
        """Handle failed payment."""
        subscription_id = data.get('subscription')

        subscription = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()

        if subscription:
            subscription.status = 'past_due'
            db.session.commit()
            logger.warning(
                "Payment failed for subscription: user_id=%d",
                subscription.user_id
            )

        return True, "Payment failure recorded"

    def cancel_subscription(self, user: User) -> Tuple[bool, str]:
        """
        Cancel user's subscription.

        Args:
            user: The user

        Returns:
            Tuple of (success, message)
        """
        if not user.stripe_subscription_id:
            return False, "No active subscription"

        try:
            # Cancel at period end (don't immediately revoke access)
            stripe.Subscription.modify(
                user.stripe_subscription_id,
                cancel_at_period_end=True,
            )

            subscription = Subscription.query.filter_by(
                stripe_subscription_id=user.stripe_subscription_id
            ).first()

            if subscription:
                subscription.cancel_at = datetime.now(timezone.utc)
                db.session.commit()

            logger.info("Subscription cancellation scheduled: user_id=%d", user.id)
            return True, "Subscription will be canceled at the end of the billing period"

        except stripe.error.StripeError as e:
            logger.error("Stripe error: %s", str(e))
            return False, f"Failed to cancel: {str(e)}"
