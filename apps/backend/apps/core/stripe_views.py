import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from apps.core.billing import handle_stripe_event


@csrf_exempt
def stripe_webhook(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponseBadRequest('Stripe webhook is not configured')

    payload = request.body
    signature = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponseBadRequest('Invalid Stripe webhook payload')

    handle_stripe_event(event, request=request)
    return HttpResponse(status=200)
