import csv
import io
import base64
import mimetypes
from datetime import datetime, timedelta
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login, logout
from django.core.mail import send_mail
from django.utils.html import escape
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.db.models import Q
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import qrcode
import qrcode.image.svg

from apps.accounts.models import MerchantMembership, StaffMFA
from apps.campaigns.models import Campaign, EntryPoint, WheelSegment
from apps.core.forms import CampaignForm, EntryPointForm, MerchantForm, MerchantReviewForm, MerchantSignupForm, RewardForm, StaffMerchantCreateForm
from apps.core.totp import generate_secret, provisioning_uri, verify_totp
from apps.core.utils import build_qr_svg, generate_qr_data_uri
from apps.core.security import rate_limit
from apps.customers.forms import ClaimRewardForm
from apps.customers.models import Customer, GameSession, WalletPass
from apps.customers.services import claim_reward, reward_claim_url, send_reward_notifications
from apps.customers.wallet import build_wallet_payload, issue_wallet_pass_placeholder, wallet_config_status
from apps.merchants.models import Merchant
from apps.rewards.models import Reward

def _current_merchant(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    return membership.merchant if membership else None

def _first_membership(user):
    return MerchantMembership.objects.select_related('merchant').filter(user=user).first()

def _merchant_is_unlocked(merchant):
    if merchant and merchant.is_demo and merchant.demo_expires_at and merchant.demo_expires_at < timezone.now():
        return False
    return bool(merchant and merchant.is_active)

def _merchant_logo_for_svg(merchant):
    """Return an embeddable logo URI for QR SVGs.

    Browsers/printers often block nested external images when an SVG is opened
    directly or downloaded. Embedding uploaded logos as data URIs makes the QR
    self-contained and keeps the branding visible everywhere.
    """
    if not merchant:
        return None
    if merchant.logo and merchant.logo.name:
        try:
            with merchant.logo.open('rb') as logo_file:
                raw = logo_file.read()
            content_type = mimetypes.guess_type(merchant.logo.name)[0] or 'image/png'
            return f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception:
            return merchant.logo.url
    return merchant.logo_url or None

def _pricing_plans():
    return [
        {
            'key': 'all_inclusive',
            'name': 'Tout inclus',
            'price': '90€ TTC / mois',
            'tagline': 'Une offre simple pour lancer Growlee dans votre restaurant.',
            'features': ['Parcours QR mobile premium', 'Jeu cadeau', 'Avis Google + feedback privé', 'Wallet fidélité', 'Notifications push Apple Wallet', 'Campagnes SMS & Email', 'Personnalisation logo/couleurs', 'Clients cloisonnés par commerce'],
            'payment_link': settings.GROWLEE_PAYMENT_LINK_PRO,
            'highlight': True,
            'cta': 'Acheter maintenant',
        },
        {
            'key': 'multi_restaurant',
            'name': 'Multi-restaurants',
            'price': 'Sur devis',
            'tagline': 'Pour les groupes, franchises ou plusieurs établissements.',
            'features': ['Plusieurs restaurants', 'Gestion centralisée', 'Offres et modules par établissement', 'Accompagnement au lancement', 'Tarif adapté au volume'],
            'payment_link': '',
            'contact': True,
            'cta': 'Contactez-nous',
        },
    ]

def _employee_mode_block_response(request):
    allowed_paths = {'/admin/employee/', '/admin/employee/exit/', '/logout/'}
    if request.session.get('growlee_employee_mode') and request.path not in allowed_paths:
        return redirect('employee-mode')
    return None

def _admin_access_block_response(request, merchant=None):
    employee_block = _employee_mode_block_response(request)
    if employee_block is not None:
        return employee_block
    if request.user.is_superuser:
        return redirect('staff-merchants')
    membership = _first_membership(request.user)
    merchant = merchant or (membership.merchant if membership else None)
    if merchant is None:
        messages.error(request, 'Aucun commerce n’est rattaché à ce compte.')
        return redirect('logout')
    onboarding_allowed = {
        '/admin/account/',
        '/admin/onboarding/',
        '/admin/checkout/',
        '/logout/',
    }
    if not _merchant_is_unlocked(merchant) and request.path not in onboarding_allowed:
        return render(request, 'admin/pending_payment.html', {'merchant': merchant, 'pricing_plans': _pricing_plans()})
    if request.path not in onboarding_allowed:
        billing_validated = merchant.is_active and merchant.onboarding_fee_paid
        if not billing_validated:
            if not merchant.onboarding_completed:
                messages.info(request, 'Complétez l’onboarding commerçant pour personnaliser votre interface Growlee.')
                return redirect('merchant-account')
            if not merchant.flyer_style or not merchant.flyer_visual_approved:
                messages.info(request, 'Validez votre flyer pour débloquer votre dashboard et préparer le paiement.')
                return redirect('merchant-account')
        dashboard_preview_allowed = {'/admin/'}
        if not billing_validated and request.path not in dashboard_preview_allowed:
            messages.info(request, 'Votre dashboard et votre QR sont prêts. Finalisez le paiement onboarding pour débloquer toute l’application.')
            return redirect('admin-dashboard')
    return None

def merchant_unlocked_required(view_func):
    def wrapper(request, *args, **kwargs):
        blocked = _admin_access_block_response(request)
        if blocked is not None:
            return blocked
        return view_func(request, *args, **kwargs)
    return wrapper

def _unique_merchant_slug(name):
    base = slugify(name) or 'commerce'
    slug = base[:48]
    counter = 2
    while Merchant.objects.filter(slug=slug).exists():
        suffix = f'-{counter}'
        slug = f"{base[:48-len(suffix)]}{suffix}"
        counter += 1
    return slug

def _control_access_granted(request):
    return bool(request.session.get('growlee_control_2fa_ok'))

def _is_superuser(user):
    return bool(user.is_authenticated and user.is_active and user.is_superuser)

superuser_required = user_passes_test(_is_superuser, login_url='/login/')

def _staff_mfa_for_user(user):
    mfa, _ = StaffMFA.objects.get_or_create(user=user, defaults={'secret': generate_secret()})
    if not mfa.secret:
        mfa.secret = generate_secret()
        mfa.save(update_fields=['secret', 'updated_at'])
    return mfa

def _staff_mfa_qr_context(user, mfa=None):
    mfa = mfa or _staff_mfa_for_user(user)
    uri = provisioning_uri(mfa.secret, user.username)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    img.save(buffer)
    return {
        'mfa': mfa,
        'qr_svg': buffer.getvalue().decode('utf-8'),
        'secret': mfa.secret,
        'otpauth_uri': uri,
    }

def _get_active_campaign_for_merchant(merchant):
    if merchant is None:
        return None
    # Le parcours client suit la campagne courante du commerçant.
    # Si la dernière campagne / le module Jeu est désactivé côté admin,
    # on ne retombe pas sur une ancienne campagne active : le parcours est coupé aussi.
    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    return campaign if campaign and campaign.is_active else None

def _merchant_context_for_user(user):
    membership = _first_membership(user)
    merchant = membership.merchant if membership else None
    campaigns = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id') if merchant else Campaign.objects.none()
    # L'admin doit refléter la campagne que l'utilisateur vient de modifier,
    # même si elle est désactivée. Sinon le dashboard retombe sur une ancienne
    # campagne active et les toggles semblent ne pas se mettre à jour.
    campaign = campaigns.first()
    entry_points = EntryPoint.objects.filter(merchant=merchant) if merchant else []
    primary_entry = entry_points.order_by('created_at', 'id').first() if merchant else None
    rewards = Reward.objects.filter(merchant=merchant) if merchant else []
    customers = Customer.objects.filter(merchant=merchant).order_by('-created_at')[:10] if merchant else []
    distributed = GameSession.objects.filter(campaign__merchant=merchant).count() if merchant else 0
    redeemed = GameSession.objects.filter(campaign__merchant=merchant, redeemed=True).count() if merchant else 0
    gains_won = GameSession.objects.filter(campaign__merchant=merchant, is_winner=True).count() if merchant else 0
    gains_waiting = GameSession.objects.filter(campaign__merchant=merchant, is_winner=True, redeemed=False).count() if merchant else 0
    now = timezone.now()
    active_campaigns = campaigns.filter(is_active=True).filter(
        Q(send_immediately=True) | Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=now)
    )
    scheduled_campaigns = campaigns.filter(is_active=True, send_immediately=False, scheduled_for__gt=now)
    stats = {
        'scans': distributed,
        'contacts': Customer.objects.filter(merchant=merchant).count() if merchant else 0,
        'wallets': redeemed,
        'return_rate': f"{int((redeemed / distributed) * 100) if distributed else 0}%",
        'distributed': distributed,
        'redeemed': redeemed,
        'gains_won': gains_won,
        'gains_waiting': gains_waiting,
        'review_clicks': 0,
        'review_target': 20,
        'campaigns_live': active_campaigns.count(),
        'campaigns_scheduled': scheduled_campaigns.count(),
    }
    game_active = bool(campaign and campaign.is_active)
    review_active = bool(campaign and campaign.review_enabled)
    wallet_active = bool(campaign and campaign.wallet_enabled)
    return {
        'merchant': merchant,
        'campaign': campaign,
        'campaigns': campaigns,
        'active_campaigns': active_campaigns[:5],
        'scheduled_campaigns': scheduled_campaigns[:5],
        'entry_points': entry_points,
        'primary_entry': primary_entry,
        'rewards': rewards,
        'customers': customers,
        'stats': stats,
        'game_active': game_active,
        'review_active': review_active,
        'wallet_active': wallet_active,
        'active_modules_count': int(game_active) + int(review_active) + int(wallet_active),
    }

def _ensure_default_growlee_setup(merchant):
    campaign, _ = Campaign.objects.get_or_create(
        merchant=merchant,
        name='Campagne de bienvenue',
        defaults={
            'game_type': 'spin',
            'reward_label': 'Offre exclusive sur votre prochaine visite',
            'landing_headline': 'Tentez votre chance',
            'landing_subheadline': 'Un jeu rapide pour découvrir votre surprise du jour.',
            'cta_label': 'Jouer maintenant',
            'journey_type': 'premium_mobile',
            'review_enabled': True,
            'wallet_enabled': True,
            'is_active': True,
        },
    )

    entry_point, _ = EntryPoint.objects.get_or_create(
        merchant=merchant,
        campaign=campaign,
        code=f'{merchant.slug}-qr-main',
        defaults={
            'name': 'QR principal',
            'channel': 'qr',
            'placement': 'counter',
        },
    )

    reward, _ = Reward.objects.get_or_create(
        merchant=merchant,
        campaign=campaign,
        name='Offre de bienvenue',
        defaults={
            'reward_type': 'custom',
            'description': 'Offre exclusive sur votre prochaine visite',
            'probability_weight': 100,
            'daily_quota': 50,
            'active': True,
            'expires_in_hours': 168,
        },
    )

    if not WheelSegment.objects.filter(campaign=campaign).exists():
        WheelSegment.objects.create(campaign=campaign, reward=reward, label='Gain principal', probability_weight=65, daily_quota=50, display_order=1, color='#f59e0b', active=True)
        WheelSegment.objects.create(campaign=campaign, reward=reward, label='Petit bonus', probability_weight=25, daily_quota=50, display_order=2, color='#fb7185', active=True)
        WheelSegment.objects.create(campaign=campaign, reward=reward, label='Jackpot', probability_weight=10, daily_quota=20, display_order=3, color='#60a5fa', active=True)

    return campaign, entry_point, reward

def _ensure_spin_defaults(campaign):
    if campaign is None or campaign.game_type not in {'spin', 'scratch'}:
        return
    active_segments = WheelSegment.objects.filter(campaign=campaign, active=True)
    if active_segments.count() >= 3:
        return
    reward = Reward.objects.filter(campaign=campaign, active=True).order_by('-probability_weight', 'id').first()
    defaults = [
        ('Gain principal', 65, 50, 1, '#f59e0b'),
        ('Petit bonus', 25, 50, 2, '#fb7185'),
        ('Jackpot', 10, 20, 3, '#60a5fa'),
    ]
    existing_labels = set(active_segments.values_list('label', flat=True))
    for label, weight, quota, order, color in defaults:
        if label in existing_labels:
            continue
        WheelSegment.objects.create(campaign=campaign, reward=reward, label=label, probability_weight=weight, daily_quota=quota, display_order=order, color=color, active=True)

def _font_stack(font_key):
    mapping = {
        'inter': 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        'poppins': 'Poppins, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        'manrope': 'Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        'dm-sans': '"DM Sans", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    }
    return mapping.get(font_key, mapping['inter'])

def _latest_session_for_wallet(request, slug):
    merchant = get_object_or_404(Merchant, slug=slug, is_active=True)
    campaign = _get_active_campaign_for_merchant(merchant)
    session_id = request.session.get(f'growlee_last_session_{merchant.slug}')
    session = None
    if session_id and campaign:
        session = GameSession.objects.filter(id=session_id, campaign=campaign).select_related('customer', 'campaign__merchant', 'reward').first()
    if session is None and campaign:
        session = GameSession.objects.filter(campaign=campaign).select_related('customer', 'campaign__merchant', 'reward').order_by('-created_at').first()
    if session is None:
        raise Http404('Aucune session de jeu disponible pour générer le wallet.')
    return session

