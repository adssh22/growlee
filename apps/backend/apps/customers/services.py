import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.utils import timezone

from apps.campaigns.models import WheelSegment
from apps.customers.models import Customer, GameSession
from apps.rewards.models import Reward


def _pick_reward_for_campaign(*, merchant, campaign):
    if campaign.game_type in {'spin', 'scratch'}:
        segments = list(
            WheelSegment.objects.filter(campaign=campaign, active=True).select_related('reward').order_by('display_order', 'id')
        )
        weighted_segments = [segment for segment in segments if segment.probability_weight > 0]
        if weighted_segments:
            chosen = random.choices(weighted_segments, weights=[segment.probability_weight for segment in weighted_segments], k=1)[0]
            return chosen.reward, chosen.label, chosen

    reward = Reward.objects.filter(merchant=merchant, active=True).filter(campaign=campaign).order_by('-probability_weight', 'id').first()
    if reward is None:
        reward = Reward.objects.filter(merchant=merchant, active=True, campaign__isnull=True).order_by('-probability_weight', 'id').first()
    if reward:
        return reward, reward.description, None
    return None, campaign.reward_label, None


def claim_reward(*, merchant, campaign, phone: str, email: str = '', first_name: str = '', consent: bool = False):
    normalized_phone = ''.join(ch for ch in phone if ch.isdigit() or ch == '+').strip()
    customer, _ = Customer.objects.get_or_create(
        merchant=merchant,
        phone=normalized_phone,
        defaults={
            'email': email or None,
            'first_name': first_name or '',
            'consent_marketing': consent,
        },
    )

    updated = False
    if email and customer.email != email:
        customer.email = email
        updated = True
    if first_name and customer.first_name != first_name:
        customer.first_name = first_name
        updated = True
    if consent and not customer.consent_marketing:
        customer.consent_marketing = True
        updated = True
    if updated:
        customer.save(update_fields=['email', 'first_name', 'consent_marketing'])

    reward, reward_label, segment = _pick_reward_for_campaign(merchant=merchant, campaign=campaign)

    session = GameSession.objects.create(
        customer=customer,
        campaign=campaign,
        reward_label=reward_label,
        reward=reward,
        claim_code=secrets.token_hex(4).upper(),
        claim_token=secrets.token_urlsafe(32),
        is_winner=True,
        redeemed=False,
        reward_expires_at=timezone.now() + timedelta(hours=(reward.expires_in_hours if reward else 168)),
    )
    if reward:
        reward.total_distributed += 1
        reward.save(update_fields=['total_distributed'])
    return customer, session, segment


def reward_claim_url(session):
    return f"{settings.APP_BASE_URL}{reverse('reward-claim-page', kwargs={'token': session.claim_token})}"


def send_reward_notifications(session):
    """Envoie le lien unique du gain par email et prépare le canal SMS.

    En dev, l'email sort sur console par défaut. Le SMS reste volontairement
    en console tant qu'un provider (Twilio/Brevo/OVH) n'est pas branché.
    """
    customer = session.customer
    url = reward_claim_url(session)
    merchant = session.campaign.merchant
    if customer.email:
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
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [customer.email])
        msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=True)
    if settings.SMS_BACKEND == 'console' and customer.phone:
        print(f"[Growlee SMS] À {customer.phone}: Votre gain {session.reward_label} chez {merchant.name}: {url}")
