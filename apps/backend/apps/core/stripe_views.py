import logging

import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from apps.core.billing import handle_stripe_event
from apps.core.logging_utils import short_identifier

logger = logging.getLogger(__name__)


def _event_value(event, key, default=''):
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


@csrf_exempt
def stripe_webhook(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.warning('Stripe webhook ignored: webhook secret not configured')
        return HttpResponseBadRequest('Stripe webhook is not configured')

    payload = request.body
    signature = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        logger.warning('Stripe webhook error: invalid payload or signature error_type=%s', exc.__class__.__name__)
        return HttpResponseBadRequest('Invalid Stripe webhook payload')

    event_type = _event_value(event, 'type')
    event_id = _event_value(event, 'id')
    logger.info('Stripe webhook received event_type=%s event_id=%s', event_type, short_identifier(event_id))
    try:
        handle_stripe_event(event, request=request)
    except Exception:
        logger.exception('Stripe webhook error while handling event_type=%s event_id=%s', event_type, short_identifier(event_id))
        raise
    return HttpResponse(status=200)
