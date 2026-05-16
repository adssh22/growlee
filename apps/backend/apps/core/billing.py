import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction

from apps.core.audit import log_audit_event
from apps.merchants.models import Merchant, Subscription

logger = logging.getLogger(__name__)

STRIPE_TO_SUBSCRIPTION_STATUS = {
    'active': Subscription.STATUS_ACTIVE,
    'trialing': Subscription.STATUS_TRIALING,
    'past_due': Subscription.STATUS_PAST_DUE,
    'canceled': Subscription.STATUS_CANCELED,
    'incomplete_expired': Subscription.STATUS_CANCELED,
    'unpaid': Subscription.STATUS_SUSPENDED,
    'incomplete': Subscription.STATUS_SUSPENDED,
    'paused': Subscription.STATUS_SUSPENDED,
}


def stripe_configured():
    return bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PRICE_ID_PRO)


def map_stripe_subscription_status(stripe_status):
    return STRIPE_TO_SUBSCRIPTION_STATUS.get((stripe_status or '').strip().lower(), Subscription.STATUS_SUSPENDED)


def _datetime_from_timestamp(value):
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)


def _metadata(obj):
    metadata = getattr(obj, 'metadata', None)
    if metadata is None and isinstance(obj, dict):
        metadata = obj.get('metadata')
    return metadata or {}


def _get_value(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _find_merchant_from_stripe_object(obj):
    metadata = _metadata(obj)
    merchant_id = metadata.get('merchant_id')
    if merchant_id:
        merchant = Merchant.objects.filter(id=merchant_id).first()
        if merchant:
            return merchant

    subscription_id = _get_value(obj, 'subscription') or _get_value(obj, 'id')
    customer_id = _get_value(obj, 'customer')
    filters = []
    if subscription_id:
        filters.append({'subscription__provider_subscription_id': subscription_id})
    if customer_id:
        filters.append({'subscription__provider_customer_id': customer_id})
    for query in filters:
        merchant = Merchant.objects.filter(**query).first()
        if merchant:
            return merchant
    return None


def _subscription_defaults_from_stripe(obj, *, status=None):
    stripe_status = status or _get_value(obj, 'status')
    return {
        'plan': Subscription.PLAN_PRO,
        'status': map_stripe_subscription_status(stripe_status),
        'provider': Subscription.PROVIDER_STRIPE,
        'provider_customer_id': _get_value(obj, 'customer') or '',
        'provider_subscription_id': _get_value(obj, 'id') or _get_value(obj, 'subscription') or '',
        'current_period_start': _datetime_from_timestamp(_get_value(obj, 'current_period_start')),
        'current_period_end': _datetime_from_timestamp(_get_value(obj, 'current_period_end')),
        'trial_ends_at': _datetime_from_timestamp(_get_value(obj, 'trial_end')),
        'canceled_at': _datetime_from_timestamp(_get_value(obj, 'canceled_at')),
    }


def _update_subscription(merchant, defaults):
    defaults = {key: value for key, value in defaults.items() if value not in {None, ''} or key in {'provider_customer_id', 'provider_subscription_id'}}
    subscription, _created = Subscription.objects.update_or_create(
        merchant=merchant,
        defaults=defaults,
    )
    return subscription


def _mark_paid_merchant(merchant):
    update_fields = []
    if not merchant.onboarding_fee_paid:
        merchant.onboarding_fee_paid = True
        update_fields.append('onboarding_fee_paid')
    if not merchant.is_active:
        merchant.is_active = True
        update_fields.append('is_active')
    if update_fields:
        merchant.save(update_fields=update_fields)


def handle_checkout_session_completed(session, request=None):
    merchant = _find_merchant_from_stripe_object(session)
    if merchant is None:
        logger.warning('Stripe checkout.session.completed without matching merchant: %s', _get_value(session, 'id'))
        return None

    with transaction.atomic():
        _mark_paid_merchant(merchant)
        defaults = {
            'plan': Subscription.PLAN_PRO,
            'status': Subscription.STATUS_ACTIVE,
            'provider': Subscription.PROVIDER_STRIPE,
            'provider_customer_id': _get_value(session, 'customer') or '',
            'provider_subscription_id': _get_value(session, 'subscription') or '',
        }
        subscription = _update_subscription(merchant, defaults)
        log_audit_event(request, 'billing.stripe.checkout_completed', target=subscription, merchant=merchant, metadata={
            'stripe_session_id': _get_value(session, 'id'),
            'stripe_customer_id': _get_value(session, 'customer'),
            'stripe_subscription_id': _get_value(session, 'subscription'),
        })
    return subscription


def handle_stripe_subscription_event(subscription_obj, request=None):
    merchant = _find_merchant_from_stripe_object(subscription_obj)
    if merchant is None:
        logger.warning('Stripe subscription event without matching merchant: %s', _get_value(subscription_obj, 'id'))
        return None

    with transaction.atomic():
        defaults = _subscription_defaults_from_stripe(subscription_obj)
        subscription = _update_subscription(merchant, defaults)
        if subscription.status in {Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING}:
            _mark_paid_merchant(merchant)
        log_audit_event(request, 'billing.stripe.subscription_update', target=subscription, merchant=merchant, metadata={
            'stripe_subscription_id': _get_value(subscription_obj, 'id'),
            'stripe_status': _get_value(subscription_obj, 'status'),
            'mapped_status': subscription.status,
        })
    return subscription


def handle_invoice_payment_failed(invoice, request=None):
    merchant = _find_merchant_from_stripe_object(invoice)
    if merchant is None:
        logger.warning('Stripe invoice.payment_failed without matching merchant: %s', _get_value(invoice, 'id'))
        return None

    with transaction.atomic():
        subscription = _update_subscription(merchant, {
            'plan': Subscription.PLAN_PRO,
            'status': Subscription.STATUS_PAST_DUE,
            'provider': Subscription.PROVIDER_STRIPE,
            'provider_customer_id': _get_value(invoice, 'customer') or '',
            'provider_subscription_id': _get_value(invoice, 'subscription') or '',
        })
        log_audit_event(request, 'billing.stripe.payment_failed', target=subscription, merchant=merchant, metadata={
            'stripe_invoice_id': _get_value(invoice, 'id'),
            'stripe_subscription_id': _get_value(invoice, 'subscription'),
        })
    return subscription


def handle_invoice_payment_succeeded(invoice, request=None):
    merchant = _find_merchant_from_stripe_object(invoice)
    if merchant is None:
        logger.warning('Stripe invoice.payment_succeeded without matching merchant: %s', _get_value(invoice, 'id'))
        return None

    with transaction.atomic():
        _mark_paid_merchant(merchant)
        subscription = _update_subscription(merchant, {
            'plan': Subscription.PLAN_PRO,
            'status': Subscription.STATUS_ACTIVE,
            'provider': Subscription.PROVIDER_STRIPE,
            'provider_customer_id': _get_value(invoice, 'customer') or '',
            'provider_subscription_id': _get_value(invoice, 'subscription') or '',
        })
        log_audit_event(request, 'billing.stripe.payment_succeeded', target=subscription, merchant=merchant, metadata={
            'stripe_invoice_id': _get_value(invoice, 'id'),
            'stripe_subscription_id': _get_value(invoice, 'subscription'),
        })
    return subscription


def handle_stripe_event(event, request=None):
    event_type = _get_value(event, 'type')
    data = _get_value(event, 'data', {}) or {}
    obj = data.get('object') if isinstance(data, dict) else getattr(data, 'object', None)

    if event_type == 'checkout.session.completed':
        return handle_checkout_session_completed(obj, request=request)
    if event_type in {'customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted'}:
        return handle_stripe_subscription_event(obj, request=request)
    if event_type == 'invoice.payment_failed':
        return handle_invoice_payment_failed(obj, request=request)
    if event_type == 'invoice.payment_succeeded':
        return handle_invoice_payment_succeeded(obj, request=request)
    logger.info('Ignoring unsupported Stripe event type=%s', event_type)
    return None
