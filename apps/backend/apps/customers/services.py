import random
import secrets
from datetime import datetime, time, timedelta

import phonenumbers
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from apps.campaigns.models import WheelSegment
from apps.customers.models import Customer, GameSession, NotificationJob
from apps.rewards.models import Reward


def _today_bounds():
    current_tz = timezone.get_current_timezone()
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, time.min), current_tz)
    return start, start + timedelta(days=1)


def _distributed_today_query():
    start, end = _today_bounds()
    return GameSession.objects.filter(created_at__gte=start, created_at__lt=end)


def _reward_quota_available(reward):
    if reward is None:
        return True
    if reward.daily_quota <= 0:
        return False
    distributed_today = _distributed_today_query().filter(reward=reward).count()
    return distributed_today < reward.daily_quota


def _segment_quota_available(segment):
    if segment.daily_quota <= 0:
        return False
    distributed_today = _distributed_today_query().filter(campaign=segment.campaign, reward_label=segment.label).count()
    return distributed_today < segment.daily_quota and _reward_quota_available(segment.reward)


def _weighted_choice(items, weight_attr='probability_weight'):
    weighted_items = [item for item in items if getattr(item, weight_attr) > 0]
    if not weighted_items:
        return None
    return random.choices(weighted_items, weights=[getattr(item, weight_attr) for item in weighted_items], k=1)[0]


def _pick_reward_for_campaign(*, merchant, campaign):
    if campaign.game_type in {'spin', 'scratch'}:
        segments = list(
            WheelSegment.objects.filter(campaign=campaign, active=True)
            .filter(Q(reward__isnull=True) | Q(reward__archived_at__isnull=True))
            .select_related('reward')
            .order_by('display_order', 'id')
        )
        weighted_segments = [segment for segment in segments if segment.probability_weight > 0]
        available_segments = [segment for segment in weighted_segments if _segment_quota_available(segment)]
        chosen = _weighted_choice(available_segments)
        if chosen:
            return chosen.reward, chosen.label, chosen, True
        if weighted_segments:
            return None, 'Aucun gain disponible aujourd’hui', None, False

    rewards = list(
        Reward.objects.filter(merchant=merchant, active=True, archived_at__isnull=True)
        .filter(Q(campaign=campaign) | Q(campaign__isnull=True))
        .order_by('-probability_weight', 'id')
    )
    available_rewards = [reward for reward in rewards if _reward_quota_available(reward)]
    reward = _weighted_choice(available_rewards)
    if reward:
        return reward, reward.description, None, True
    if rewards:
        return None, 'Aucun gain disponible aujourd’hui', None, False
    return None, campaign.reward_label, None, True


def normalize_phone(phone: str) -> str:
    raw_phone = (phone or '').strip()
    if raw_phone.startswith('00'):
        raw_phone = f'+{raw_phone[2:]}'
    try:
        parsed_phone = phonenumbers.parse(raw_phone, getattr(settings, 'GROWLEE_DEFAULT_PHONE_REGION', 'FR'))
    except phonenumbers.NumberParseException as exc:
        raise ValidationError('Numéro de téléphone invalide.') from exc
    if not phonenumbers.is_valid_number(parsed_phone):
        raise ValidationError('Numéro de téléphone invalide.')
    return phonenumbers.format_number(parsed_phone, phonenumbers.PhoneNumberFormat.E164)


def _play_cooldown_delta():
    cooldown_hours = int(getattr(settings, 'GROWLEE_PLAY_COOLDOWN_HOURS', 24) or 0)
    if cooldown_hours <= 0:
        return None
    return timedelta(hours=cooldown_hours)


def _ensure_phone_can_play(*, merchant, normalized_phone):
    cooldown = _play_cooldown_delta()
    if cooldown is None:
        return
    cutoff = timezone.now() - cooldown
    played_recently = GameSession.objects.filter(
        customer__merchant=merchant,
        customer__phone=normalized_phone,
        created_at__gte=cutoff,
    ).exists()
    if played_recently:
        raise ValidationError('Ce numéro a déjà joué récemment chez ce commerce. Réessaie plus tard.')


def claim_reward(*, merchant, campaign, phone: str, email: str = '', first_name: str = '', consent_marketing: bool = False):
    normalized_phone = normalize_phone(phone)
    _ensure_phone_can_play(merchant=merchant, normalized_phone=normalized_phone)
    consent_marketing_at = timezone.now() if consent_marketing else None
    customer, _ = Customer.objects.get_or_create(
        merchant=merchant,
        phone=normalized_phone,
        defaults={
            'email': email or None,
            'first_name': first_name or '',
            'consent_marketing': consent_marketing,
            'consent_marketing_at': consent_marketing_at,
        },
    )

    update_fields = []
    if customer.deleted_at:
        customer.deleted_at = None
        customer.deleted_by = None
        update_fields.extend(['deleted_at', 'deleted_by'])
    if email and customer.email != email:
        customer.email = email
        update_fields.append('email')
    if first_name and customer.first_name != first_name:
        customer.first_name = first_name
        update_fields.append('first_name')
    if consent_marketing and not customer.consent_marketing:
        customer.consent_marketing = True
        customer.consent_marketing_at = consent_marketing_at or timezone.now()
        update_fields.extend(['consent_marketing', 'consent_marketing_at'])
    if update_fields:
        customer.save(update_fields=update_fields)

    reward, reward_label, segment, is_winner = _pick_reward_for_campaign(merchant=merchant, campaign=campaign)

    session = GameSession.objects.create(
        customer=customer,
        campaign=campaign,
        reward_label=reward_label,
        reward=reward,
        claim_code=secrets.token_hex(4).upper(),
        claim_token=secrets.token_urlsafe(32),
        is_winner=is_winner,
        redeemed=False,
        reward_expires_at=timezone.now() + timedelta(hours=(reward.expires_in_hours if reward else 168)),
    )
    if reward and is_winner:
        Reward.objects.filter(pk=reward.pk).update(total_distributed=F('total_distributed') + 1)
    return customer, session, segment


def reward_claim_url(session):
    return f"{settings.APP_BASE_URL}{reverse('reward-claim-page', kwargs={'token': session.claim_token})}"


def send_sms(to_phone: str, body: str) -> bool:
    provider = getattr(settings, 'SMS_PROVIDER', 'console') or 'console'
    provider = provider.lower()
    if not to_phone:
        return False
    if provider in {'console', 'debug'}:
        print(f"[Growlee SMS] À {to_phone}: {body}")
        return True
    if provider == 'twilio':
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER):
            print('[Growlee SMS] Twilio non configuré: SID/TOKEN/FROM manquant')
            return False
        response = requests.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json',
            data={'From': settings.TWILIO_FROM_NUMBER, 'To': to_phone, 'Body': body},
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            timeout=10,
        )
        if response.status_code >= 300:
            print(f'[Growlee SMS] Twilio erreur {response.status_code}: {response.text[:300]}')
            return False
        return True
    if provider == 'brevo':
        if not settings.BREVO_API_KEY:
            print('[Growlee SMS] Brevo non configuré: BREVO_API_KEY manquant')
            return False
        response = requests.post(
            'https://api.brevo.com/v3/transactionalSMS/sms',
            headers={'api-key': settings.BREVO_API_KEY, 'Content-Type': 'application/json', 'Accept': 'application/json'},
            json={'sender': settings.BREVO_SMS_SENDER, 'recipient': to_phone, 'content': body},
            timeout=10,
        )
        if response.status_code >= 300:
            print(f'[Growlee SMS] Brevo erreur {response.status_code}: {response.text[:300]}')
            return False
        return True
    print(f'[Growlee SMS] Provider inconnu: {provider}')
    return False


def _email_provider():
    return getattr(settings, 'EMAIL_PROVIDER', '') or settings.EMAIL_BACKEND.rsplit('.', 1)[-1]


def _notification_provider(channel):
    if channel == NotificationJob.CHANNEL_EMAIL:
        return _email_provider()
    if channel == NotificationJob.CHANNEL_SMS:
        return getattr(settings, 'SMS_PROVIDER', 'console') or 'console'
    return ''


def enqueue_reward_notifications(session, *, scheduled_at=None):
    """Create durable notification jobs for a reward session.

    Celery/RQ can later enqueue this function's pending jobs; for now the
    management command owns dispatch. In local/dev, set NOTIFICATION_SEND_SYNC=1
    to process the freshly-created jobs immediately.
    """
    if not session.is_winner:
        return []
    session = GameSession.objects.select_related('customer', 'campaign__merchant').get(pk=session.pk)
    customer = session.customer
    merchant = session.campaign.merchant
    scheduled_at = scheduled_at or timezone.now()
    jobs = []
    channels = []
    if customer.email:
        channels.append(NotificationJob.CHANNEL_EMAIL)
    if customer.phone:
        channels.append(NotificationJob.CHANNEL_SMS)
    for channel in channels:
        job, _ = NotificationJob.objects.get_or_create(
            game_session=session,
            channel=channel,
            defaults={
                'merchant': merchant,
                'customer': customer,
                'provider': _notification_provider(channel),
                'scheduled_at': scheduled_at,
            },
        )
        jobs.append(job)
    if getattr(settings, 'NOTIFICATION_SEND_SYNC', False):
        for job in jobs:
            process_notification_job(job)
    return jobs


def _reward_email_payload(session):
    customer = session.customer
    merchant = session.campaign.merchant
    url = reward_claim_url(session)
    subject = f"Votre gain chez {merchant.name}"
    text = (
        f"Bonjour {customer.first_name or ''},\n\n"
        f"Votre gain : {session.reward_label}.\n"
        f"Il est valable jusqu'au {session.reward_expires_at:%d/%m/%Y}.\n"
        f"Ouvrez votre lien unique : {url}\n\n"
        "Quand vous cliquerez sur “Récupérer mon gain”, il sera disponible 15 minutes en point de vente."
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;background:#f7f6ff;padding:28px;color:#17152b">
      <div style="max-width:560px;margin:auto;background:#fff;border-radius:28px;padding:30px;box-shadow:0 24px 70px rgba(39,32,91,.12)">
        <div style="font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#534ab7">Growlee · Votre gain</div>
        <h1 style="font-size:34px;line-height:1.05;margin:14px 0 10px">{session.reward_label}</h1>
        <p style="color:#69647f;font-size:16px;line-height:1.55">Valable jusqu'au <strong>{session.reward_expires_at:%d/%m/%Y}</strong> chez {merchant.name}.</p>
        <a href="{url}" style="display:block;text-align:center;background:#534ab7;color:white;text-decoration:none;border-radius:18px;padding:16px 20px;font-weight:900;margin:24px 0">Voir mon gain</a>
        <p style="font-size:13px;color:#69647f;line-height:1.5">Attention : après avoir cliqué sur “Récupérer mon gain”, le gain sera disponible seulement 15 minutes. Présentez-le directement au point de vente.</p>
        <p style="font-size:12px;color:#9a94b3">Code gain : {session.claim_code}</p>
      </div>
    </div>
    """
    return subject, text, html


def _send_reward_email(session):
    if not session.customer.email:
        return False
    subject, text, html = _reward_email_payload(session)
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [session.customer.email])
    msg.attach_alternative(html, 'text/html')
    return bool(msg.send(fail_silently=False))


def _send_reward_sms(session):
    if not session.customer.phone:
        return False
    merchant = session.campaign.merchant
    url = reward_claim_url(session)
    return send_sms(session.customer.phone, f"Votre gain {session.reward_label} chez {merchant.name}: {url} - activez-le seulement au point de vente (15 min).")


def process_notification_job(job):
    job = NotificationJob.objects.select_related('game_session__customer', 'game_session__campaign__merchant').get(pk=job.pk)
    if job.status == NotificationJob.STATUS_SENT:
        return job
    job.attempts = F('attempts') + 1
    job.provider = job.provider or _notification_provider(job.channel)
    job.save(update_fields=['attempts', 'provider', 'updated_at'])
    job.refresh_from_db()
    try:
        if job.channel == NotificationJob.CHANNEL_EMAIL:
            ok = _send_reward_email(job.game_session)
        elif job.channel == NotificationJob.CHANNEL_SMS:
            ok = _send_reward_sms(job.game_session)
        else:
            raise ValueError(f'Unknown notification channel: {job.channel}')
        if not ok:
            raise RuntimeError('Provider returned false')
        job.status = NotificationJob.STATUS_SENT
        job.sent_at = timezone.now()
        job.last_error = ''
    except Exception as exc:
        job.status = NotificationJob.STATUS_FAILED
        job.last_error = str(exc)[:2000]
    job.save(update_fields=['status', 'sent_at', 'last_error', 'provider', 'updated_at'])
    return job


def send_reward_notifications(session):
    """Compatibility/direct sender. Prefer enqueue_reward_notifications()."""
    if not session.is_winner:
        return
    session = GameSession.objects.select_related('customer', 'campaign__merchant').get(pk=session.pk)
    if session.customer.email:
        _send_reward_email(session)
    if session.customer.phone:
        _send_reward_sms(session)
