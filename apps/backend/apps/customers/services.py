import random
import secrets

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
        is_winner=True,
        redeemed=False,
    )
    if reward:
        reward.total_distributed += 1
        reward.save(update_fields=['total_distributed'])
    return customer, session, segment
