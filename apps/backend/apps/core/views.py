import csv
import io
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login, logout
from django.utils.html import escape
from django.utils.text import slugify
from django.db.models import Q
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from django.conf import settings
from django.utils import timezone

import qrcode
import qrcode.image.svg

from apps.accounts.models import MerchantMembership, StaffMFA
from apps.campaigns.models import Campaign, EntryPoint, WheelSegment
from apps.core.forms import CampaignForm, EntryPointForm, MerchantForm, MerchantReviewForm, MerchantSignupForm, RewardForm, StaffMerchantCreateForm
from apps.core.totp import generate_secret, provisioning_uri, verify_totp
from apps.core.utils import build_qr_svg, generate_qr_data_uri
from apps.customers.forms import ClaimRewardForm
from apps.customers.models import Customer, GameSession, WalletPass
from apps.customers.services import claim_reward, reward_claim_url, send_reward_notifications
from apps.customers.wallet import build_wallet_payload, issue_wallet_pass_placeholder, wallet_config_status
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


def _current_merchant(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    return membership.merchant if membership else None


def home(request):
    return render(request, 'public/home.html')


def _first_membership(user):
    return MerchantMembership.objects.select_related('merchant').filter(user=user).first()


def _merchant_is_unlocked(merchant):
    if merchant and merchant.is_demo and merchant.demo_expires_at and merchant.demo_expires_at < timezone.now():
        return False
    return bool(merchant and merchant.is_active)


def _pricing_plans():
    return [
        {
            'key': 'all_inclusive',
            'name': 'Tout inclus',
            'price': '90€ / mois',
            'tagline': 'Une offre simple pour lancer Growlee dans votre restaurant.',
            'features': ['Parcours QR mobile premium', 'Jeu cadeau', 'Avis Google + feedback privé', 'Wallet fidélité', 'Campagnes SMS & Email', 'Personnalisation logo/couleurs', 'Clients cloisonnés par commerce'],
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
    if not _merchant_is_unlocked(merchant):
        return render(request, 'admin/pending_payment.html', {'merchant': merchant, 'pricing_plans': _pricing_plans()})
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


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('admin-dashboard')
    form = MerchantSignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        merchant = Merchant.objects.create(
            name=form.cleaned_data['business_name'],
            slug=_unique_merchant_slug(form.cleaned_data['business_name']),
            primary_color='#4e3db7',
            accent_color='#3f9d87',
            is_active=False,
        )
        MerchantMembership.objects.create(user=user, merchant=merchant, role='owner')
        campaign, _, _ = _ensure_default_growlee_setup(merchant)
        campaign.is_active = False
        campaign.review_enabled = False
        campaign.wallet_enabled = False
        campaign.save(update_fields=['is_active', 'review_enabled', 'wallet_enabled'])
        login(request, user)
        messages.success(request, 'Compte créé. Votre espace sera activé après validation du paiement.')
        return redirect('admin-dashboard')
    return render(request, 'admin/signup.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('staff-merchants')
        return redirect('admin-dashboard')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        if form.get_user().is_superuser and (request.GET.get('next') in {None, '', '/admin/'}):
            return redirect('staff-merchants')
        return redirect(request.GET.get('next') or 'admin-dashboard')
    return render(request, 'admin/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('home')


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


@superuser_required
def staff_control_mfa_setup(request):
    mfa = _staff_mfa_for_user(request.user)
    if mfa.enabled:
        messages.info(request, 'Ta 2FA est déjà activée. La réinitialisation doit être faite par un autre super utilisateur.')
        return redirect('staff-merchants' if _control_access_granted(request) else 'staff-control-verify')

    error = None

    if request.method == 'POST':
        if verify_totp(mfa.secret, request.POST.get('totp_code')):
            mfa.enabled = True
            mfa.save(update_fields=['enabled', 'updated_at'])
            request.session['growlee_control_2fa_ok'] = True
            request.session.set_expiry(60 * 60 * 4)
            messages.success(request, '2FA téléphone activée.')
            return redirect('staff-merchants')
        error = 'Code 2FA invalide. Vérifie l’heure du téléphone et réessaie.'

    context = _staff_mfa_qr_context(request.user, mfa)
    context.update({
        'error': error,
    })
    return render(request, 'admin/staff_control_mfa_setup.html', context)


@superuser_required
def staff_control_verify(request):
    if _control_access_granted(request):
        return redirect('staff-merchants')

    mfa = _staff_mfa_for_user(request.user)
    if not mfa.enabled:
        return redirect('staff-merchants')

    error = None
    if request.method == 'POST':
        if verify_totp(mfa.secret, request.POST.get('totp_code')):
            request.session['growlee_control_2fa_ok'] = True
            request.session.set_expiry(60 * 60 * 4)
            return redirect(request.GET.get('next') or 'staff-merchants')
        error = 'Code 2FA invalide.'

    return render(request, 'admin/staff_control_verify.html', {'error': error})


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
        'rewards': rewards,
        'customers': customers,
        'stats': stats,
        'game_active': game_active,
        'review_active': review_active,
        'wallet_active': wallet_active,
        'active_modules_count': int(game_active) + int(review_active) + int(wallet_active),
    }


@login_required
def admin_dashboard(request):
    if request.user.is_superuser:
        return redirect('staff-merchants')
    context = _merchant_context_for_user(request.user)
    if context['merchant'] is None:
        if request.user.is_staff:
            return redirect('staff-merchants')
        messages.error(request, 'Aucun commerce n’est rattaché à ce compte.')
        return redirect('logout')
    blocked = _admin_access_block_response(request, context['merchant'])
    if blocked is not None:
        return blocked
    return render(request, 'admin/dashboard.html', context)


@superuser_required
def staff_merchants(request):
    mfa = _staff_mfa_for_user(request.user)
    if not mfa.enabled:
        return redirect('staff-control-mfa-setup')
    if mfa.enabled and not _control_access_granted(request):
        return redirect(f'/growlee-control/verify/?next={request.path}')

    form = StaffMerchantCreateForm(request.POST or None)
    mfa_error = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'reset_staff_mfa':
            target_user = get_object_or_404(User, id=request.POST.get('user_id'), is_active=True, is_superuser=True)
            if target_user.id == request.user.id:
                messages.error(request, 'Impossible de réinitialiser ta propre 2FA. Demande à un autre super utilisateur.')
                return redirect('staff-merchants')
            target_mfa = _staff_mfa_for_user(target_user)
            target_mfa.secret = generate_secret()
            target_mfa.enabled = False
            target_mfa.save(update_fields=['secret', 'enabled', 'updated_at'])
            messages.success(request, f'2FA réinitialisée pour {target_user.username}. Il devra scanner un nouveau QR au prochain accès.')
            return redirect('staff-merchants')
        if action == 'mfa_enable':
            if verify_totp(mfa.secret, request.POST.get('totp_code')):
                mfa.enabled = True
                mfa.save(update_fields=['enabled', 'updated_at'])
                request.session['growlee_control_2fa_ok'] = True
                request.session.set_expiry(60 * 60 * 4)
                messages.success(request, '2FA téléphone activée pour ce compte staff.')
                return redirect('staff-merchants')
            mfa_error = 'Code 2FA invalide. Vérifie l’heure du téléphone et réessaie.'
        if action == 'toggle':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            merchant.is_active = not merchant.is_active
            merchant.save(update_fields=['is_active'])
            messages.success(request, f'{merchant.name} est maintenant {"actif" if merchant.is_active else "désactivé"}.')
            return redirect('staff-merchants')
        if action == 'toggle_demo':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            merchant.is_demo = not merchant.is_demo
            merchant.demo_expires_at = timezone.now() + timedelta(days=14) if merchant.is_demo else None
            merchant.is_active = True if merchant.is_demo else merchant.is_active
            merchant.save(update_fields=['is_demo', 'demo_expires_at', 'is_active'])
            messages.success(request, f'Accès démo {"activé" if merchant.is_demo else "désactivé"} pour {merchant.name}.')
            return redirect('staff-merchants')
        if action == 'delete_merchant':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            confirm = (request.POST.get('confirm_name') or '').strip()
            if confirm != merchant.name:
                messages.error(request, f'Suppression annulée : tape exactement le nom du commerce ({merchant.name}).')
                return redirect('staff-merchants')
            merchant_name = merchant.name
            owner_users = [membership.user for membership in merchant.memberships.select_related('user').all()]
            merchant.delete()
            for user in owner_users:
                if not user.is_staff and not user.merchant_memberships.exists():
                    user.delete()
            messages.success(request, f'Commerce supprimé : {merchant_name}.')
            return redirect('staff-merchants')
        if action == 'module_toggle':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
            if campaign is None:
                campaign, _, _ = _ensure_default_growlee_setup(merchant)
                campaign.is_active = False
                campaign.review_enabled = False
                campaign.wallet_enabled = False
                campaign.save(update_fields=['is_active', 'review_enabled', 'wallet_enabled'])
            flag = request.POST.get('flag')
            if flag == 'game':
                campaign.is_active = not campaign.is_active
                campaign.save(update_fields=['is_active'])
            elif flag == 'review':
                campaign.review_enabled = not campaign.review_enabled
                campaign.save(update_fields=['review_enabled'])
            elif flag == 'wallet':
                campaign.wallet_enabled = not campaign.wallet_enabled
                campaign.save(update_fields=['wallet_enabled'])
            messages.success(request, f'Module mis à jour pour {merchant.name}.')
            return redirect('staff-merchants')
        if action == 'create' and form.is_valid():
            with transaction.atomic():
                email = form.cleaned_data['owner_email']
                username = form.cleaned_data['owner_username'] or email
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=form.cleaned_data['owner_password'],
                )
                merchant = Merchant.objects.create(
                    name=form.cleaned_data['merchant_name'],
                    slug=_unique_merchant_slug(form.cleaned_data['merchant_name']),
                    primary_color='#4e3db7',
                    accent_color='#3f9d87',
                    is_active=form.cleaned_data['is_active'],
                    is_demo=form.cleaned_data.get('is_demo') or False,
                    demo_expires_at=(timezone.now() + timedelta(days=form.cleaned_data.get('demo_days') or 14)) if form.cleaned_data.get('is_demo') else None,
                )
                MerchantMembership.objects.create(user=user, merchant=merchant, role='owner')
                _ensure_default_growlee_setup(merchant)
            messages.success(request, f'Commerce créé : {merchant.name}. Propriétaire : {user.username}')
            return redirect('staff-merchants')

    merchants = Merchant.objects.prefetch_related('memberships__user').order_by('-created_at')
    rows = []
    for merchant in merchants:
        campaigns = Campaign.objects.filter(merchant=merchant)
        rows.append({
            'merchant': merchant,
            'owners': [m for m in merchant.memberships.all() if m.role == 'owner'],
            'campaigns_count': campaigns.count(),
            'customers_count': Customer.objects.filter(merchant=merchant).count(),
            'active_campaign': campaigns.order_by('-created_at', '-id').first(),
        })
    mfa_context = _staff_mfa_qr_context(request.user, mfa)
    staff_mfa_users = User.objects.filter(is_active=True, is_superuser=True).order_by('username')
    return render(request, 'admin/staff_merchants.html', {
        'form': form,
        'rows': rows,
        'staff_mfa_users': staff_mfa_users,
        'total_merchants': merchants.count(),
        'active_merchants': merchants.filter(is_active=True).count(),
        'total_users': User.objects.count(),
        'mfa_error': mfa_error,
        **mfa_context,
    })


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


@login_required
@merchant_unlocked_required
def merchant_onboarding(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    merchant_form = MerchantForm(request.POST or None, request.FILES or None, instance=merchant, prefix='merchant')
    if request.method == 'POST' and merchant_form.is_valid():
        merchant = merchant_form.save()
        campaign, entry_point, reward = _ensure_default_growlee_setup(merchant)
        messages.success(request, 'Identité enregistrée. Votre campagne, votre reward et votre QR principal sont prêts.')
        return redirect('merchant-onboarding')

    context = _merchant_context_for_user(request.user)
    latest_campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    qr_entry = None
    nfc_entry = None
    entry_form = None
    qr_svg = ''
    if latest_campaign:
        qr_entry, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=latest_campaign,
            code=f'{merchant.slug}-qr-main',
            defaults={'name': 'QR principal', 'channel': 'qr', 'placement': 'table'},
        )
        nfc_entry, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=latest_campaign,
            code=f'{merchant.slug}-nfc-card',
            defaults={'name': 'Carte NFC', 'channel': 'nfc', 'placement': 'carte'},
        )
        entry_form = EntryPointForm(request.POST or None, instance=qr_entry, prefix='entry')
        if request.method == 'POST' and request.POST.get('form_action') == 'entry_point' and entry_form.is_valid():
            entry_form.save()
            messages.success(request, 'Redirection QR/NFC mise à jour.')
            return redirect('merchant-onboarding')
        if qr_entry:
            logo_url = merchant.logo.url if merchant.logo else merchant.logo_url
            qr_svg = build_qr_svg(
                data=f"{settings.APP_BASE_URL}/go/{qr_entry.code}/",
                merchant_name=merchant.name,
                primary_color=merchant.primary_color,
                accent_color=merchant.accent_color,
                logo_url=logo_url,
                size=420,
            )
    context.update({'merchant_form': merchant_form, 'campaign': latest_campaign, 'qr_entry_code': qr_entry.code if qr_entry else '', 'nfc_entry_code': nfc_entry.code if nfc_entry else '', 'entry_form': entry_form, 'qr_svg': qr_svg})
    return render(request, 'admin/onboarding.html', context)


@login_required
@merchant_unlocked_required
def game_configuration(request):
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    campaign_form = CampaignForm(request.POST or None, instance=campaign, prefix='campaign')
    merchant_style_form = MerchantForm(request.POST or None, request.FILES or None, instance=merchant, prefix='merchant-style')
    reward_form = RewardForm(request.POST or None, prefix='reward', initial={
        'reward_type': 'gift',
        'probability_weight': 100,
        'daily_quota': 50,
        'expires_in_hours': 168,
        'active': True,
    })

    if request.method == 'POST':
        action = request.POST.get('form_action')
        if action == 'reward' and reward_form.is_valid():
            reward = reward_form.save(commit=False)
            reward.merchant = merchant
            reward.campaign = campaign
            reward.save()
            messages.success(request, 'Récompense ajoutée au jeu.')
            return redirect('game-configuration')
        if action == 'merchant_style' and merchant_style_form.is_valid():
            merchant_style_form.save()
            messages.success(request, 'Personnalisation du parcours client mise à jour.')
            return redirect('game-configuration')
        if action != 'merchant_style' and campaign_form.is_valid():
            campaign = campaign_form.save(commit=False)
            campaign.merchant = merchant
            campaign.save()
            if campaign.game_type in {'spin', 'scratch'}:
                _ensure_spin_defaults(campaign)
            messages.success(request, 'Configuration mini jeu mise à jour.')
            return redirect('game-configuration')

    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first() if campaign else None
    if campaign and entry_point is None:
        entry_point, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=campaign,
            code=f'{merchant.slug}-qr-main',
            defaults={'name': 'QR principal', 'channel': 'qr', 'placement': 'counter'},
        )
    segments = WheelSegment.objects.filter(campaign=campaign).select_related('reward').order_by('display_order', 'id') if campaign else []
    rewards = Reward.objects.filter(merchant=merchant).order_by('name')
    total_weight = sum(segment.probability_weight for segment in segments if segment.active)
    context.update({'campaign': campaign, 'campaign_form': campaign_form, 'segments': segments, 'total_weight': total_weight, 'merchant_form': merchant_style_form, 'rewards': rewards, 'reward_form': reward_form, 'qr_entry_code': entry_point.code if entry_point else ''})
    return render(request, 'admin/game_config.html', context)


@login_required
@merchant_unlocked_required
def review_configuration(request):
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    form = MerchantReviewForm(request.POST or None, instance=merchant, prefix='merchant-review')
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Lien Google de l’établissement mis à jour.')
        return redirect('review-configuration')
    context.update({'merchant_form': form})
    return render(request, 'admin/review.html', context)


@login_required
@merchant_unlocked_required
def toggle_campaign_flag(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    context = _merchant_context_for_user(request.user)
    campaign = context['campaign']
    campaign_id = request.POST.get('campaign_id')
    if campaign_id and context['merchant']:
        campaign = Campaign.objects.filter(id=campaign_id, merchant=context['merchant']).first()
    if campaign is None:
        messages.error(request, 'Aucune campagne à modifier.')
        return redirect('merchant-onboarding')
    flag = request.POST.get('flag')
    requested = request.POST.get('value')
    desired = (requested == '1') if requested in {'0', '1'} else None
    if flag == 'is_active':
        Campaign.objects.filter(id=campaign.id).update(is_active=(desired if desired is not None else (not campaign.is_active)))
    elif flag == 'review_enabled':
        Campaign.objects.filter(id=campaign.id).update(review_enabled=(desired if desired is not None else (not campaign.review_enabled)))
    elif flag == 'wallet_enabled':
        Campaign.objects.filter(id=campaign.id).update(wallet_enabled=(desired if desired is not None else (not campaign.wallet_enabled)))
    else:
        messages.error(request, 'Option inconnue.')
    return redirect(request.POST.get('next') or 'merchant-onboarding')



@login_required
def wallet_pass_scan(request, scan_code):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    wallet_pass = WalletPass.objects.select_related('customer', 'campaign', 'campaign__merchant').filter(scan_code=scan_code).first()
    if wallet_pass is None:
        return render(request, 'admin/wallet_scan.html', {
            'merchant': merchant,
            'wallet_pass': None,
            'customer': None,
            'campaign': None,
            'is_complete': False,
            'scan_code': scan_code,
            'scan_error': 'Aucun pass wallet ne correspond à ce code. Utilisez le QR généré dans un vrai pass client.',
        }, status=404)
    if merchant is None or wallet_pass.campaign.merchant_id != merchant.id:
        messages.error(request, 'Ce pass wallet ne correspond pas à votre commerce.')
        return redirect('admin-dashboard')

    if request.method == 'POST':
        wallet_pass.stamps = min(wallet_pass.stamps + 1, wallet_pass.stamps_target)
        wallet_pass.payload = build_wallet_payload(
            GameSession.objects.filter(customer=wallet_pass.customer, campaign=wallet_pass.campaign).select_related('customer', 'campaign__merchant', 'reward').order_by('-created_at').first(),
            wallet_pass.provider,
            wallet_pass,
        ) if GameSession.objects.filter(customer=wallet_pass.customer, campaign=wallet_pass.campaign).exists() else wallet_pass.payload
        wallet_pass.save(update_fields=['stamps', 'payload', 'updated_at'])
        messages.success(request, f'Passage validé. Total: {wallet_pass.stamps}/{wallet_pass.stamps_target}.')
        return redirect('wallet-pass-scan', scan_code=scan_code)

    return render(request, 'admin/wallet_scan.html', {
        'merchant': merchant,
        'wallet_pass': wallet_pass,
        'customer': wallet_pass.customer,
        'campaign': wallet_pass.campaign,
        'is_complete': wallet_pass.stamps >= wallet_pass.stamps_target,
    })

@login_required
@merchant_unlocked_required
def wallet_configuration(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/wallet.html', context)


@login_required
@merchant_unlocked_required
def merchant_setup(request):
    return redirect('game-configuration')
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    if campaign is None:
        campaign, entry_point, reward = _ensure_default_growlee_setup(merchant)
    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first() if campaign else EntryPoint.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    if entry_point is None:
        entry_point, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=campaign,
            code=f'{merchant.slug}-qr-main',
            defaults={'name': 'QR principal', 'channel': 'qr', 'placement': 'counter'},
        )

    created = request.GET.get('created') == '1'
    qr_entry_code = request.GET.get('entry') or (entry_point.code if entry_point else '')

    return render(request, 'admin/merchant/setup.html', {
        'merchant': merchant,
        'created': created,
        'qr_entry_code': qr_entry_code,
    })


@login_required
def qr_preview(request, code):
    entry_point = get_object_or_404(EntryPoint, code=code)
    url = f"{settings.APP_BASE_URL}/go/{entry_point.code}/"
    logo_url = entry_point.merchant.logo.url if entry_point.merchant.logo else entry_point.merchant.logo_url
    svg = build_qr_svg(
        data=url,
        merchant_name=entry_point.merchant.name,
        primary_color=entry_point.merchant.primary_color,
        accent_color=entry_point.merchant.accent_color,
        logo_url=logo_url,
    )
    return HttpResponse(svg, content_type='image/svg+xml')


def entry_redirect(request, code):
    entry_point = get_object_or_404(EntryPoint, code=code)
    target = entry_point.redirect_url or f'/play/{entry_point.merchant.slug}/'
    return redirect(target)


@login_required
@merchant_unlocked_required
def customers_list(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    query = (request.GET.get('q') or '').strip()
    customers = Customer.objects.filter(merchant=merchant).order_by('-created_at')
    if query:
        customers = customers.filter(
            Q(phone__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query)
        )
    customers = customers[:100]
    for customer in customers:
        customer.latest_session = customer.game_sessions.select_related('reward').order_by('-created_at').first()
    return render(request, 'admin/customers.html', {
        'merchant': merchant,
        'customers': customers,
        'query': query,
    })


@login_required
@merchant_unlocked_required
def customer_detail(request, customer_id):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    customer = get_object_or_404(Customer, id=customer_id, merchant=merchant)
    sessions = customer.game_sessions.select_related('campaign', 'reward').order_by('-created_at')
    return render(request, 'admin/customer_detail.html', {
        'customer': customer,
        'sessions': sessions,
    })


@login_required
@merchant_unlocked_required
def delete_customer(request, customer_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    customer = get_object_or_404(Customer, id=customer_id, merchant=merchant)
    phone = customer.phone
    customer.delete()
    messages.success(request, f'Client supprimé: {phone}.')
    return redirect('customers-list')


@login_required
@merchant_unlocked_required
def customers_export_csv(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        return redirect('admin-dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="growlee-customers-{merchant.slug}.csv"'
    writer = csv.writer(response)
    writer.writerow(['phone', 'first_name', 'email', 'created_at', 'sessions_count'])
    for customer in Customer.objects.filter(merchant=merchant).order_by('-created_at'):
        writer.writerow([
            customer.phone,
            customer.first_name,
            customer.email,
            customer.created_at.isoformat(),
            customer.game_sessions.count(),
        ])
    return response


@login_required
@merchant_unlocked_required
def rewards_list(request):
    if request.method == 'GET':
        return redirect('game-configuration')
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    rewards = Reward.objects.filter(merchant=merchant).order_by('name') if merchant else []
    reward_form = RewardForm(request.POST or None, prefix='reward', initial={
        'reward_type': 'gift',
        'probability_weight': 100,
        'daily_quota': 50,
        'expires_in_hours': 168,
        'active': True,
    })

    if request.method == 'POST' and merchant and reward_form.is_valid():
        reward = reward_form.save(commit=False)
        reward.merchant = merchant
        reward.campaign = context['campaign']
        reward.save()
        messages.success(request, 'Récompense enregistrée.')
        return redirect('game-configuration')

    context['rewards'] = rewards
    context['reward_form'] = reward_form
    return render(request, 'admin/rewards.html', context)


@login_required
@merchant_unlocked_required
def reward_delete(request, reward_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    reward = get_object_or_404(Reward, id=reward_id, merchant=merchant)
    reward.delete()
    messages.success(request, 'Récompense supprimée.')
    return redirect('game-configuration')


@login_required
@merchant_unlocked_required
def analytics_view(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/analytics.html', context)


@login_required
@merchant_unlocked_required
def automations_view(request):
    context = _merchant_context_for_user(request.user)
    campaign = context['campaign']
    if request.method == 'POST' and campaign:
        schedule_enabled = request.POST.get('schedule_enabled') == '1'
        date_str = request.POST.get('scheduled_date') or ''
        time_str = request.POST.get('scheduled_time') or ''
        if schedule_enabled and date_str and time_str:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
            campaign.send_immediately = False
            campaign.scheduled_for = timezone.make_aware(dt, timezone.get_current_timezone())
        else:
            campaign.send_immediately = True
            campaign.scheduled_for = None
        campaign.save(update_fields=['send_immediately', 'scheduled_for'])
        messages.success(request, 'Planification de campagne mise à jour.')
        return redirect('automations-view')
    return render(request, 'admin/automations.html', context)


@login_required
@merchant_unlocked_required
def redeem_session(request, session_id):
    if request.method != 'POST':
        return redirect('admin-dashboard')
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    session = get_object_or_404(GameSession.objects.select_related('customer', 'campaign'), id=session_id, customer__merchant=merchant)
    if not session.redeemed:
        session.redeemed = True
        session.save(update_fields=['redeemed'])
        messages.success(request, f'Gain marqué comme utilisé pour {session.customer.phone}.')
    return redirect('customer-detail', customer_id=session.customer_id)


@login_required
@merchant_unlocked_required
def employee_mode(request):
    merchant = _current_merchant(request)
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')
    request.session['growlee_employee_mode'] = True
    found_session = None
    query = (request.POST.get('scan_code') or request.GET.get('scan_code') or '').strip()

    if request.method == 'POST' and request.POST.get('action') == 'redeem':
        session = get_object_or_404(GameSession.objects.select_related('customer', 'campaign'), id=request.POST.get('session_id'), campaign__merchant=merchant)
        if session.redeemed:
            messages.info(request, 'Ce gain a déjà été utilisé.')
        elif not session.is_recovery_window_open:
            messages.error(request, 'Fenêtre expirée : le client doit recliquer sur “Récupérer mon gain”.')
        else:
            session.redeemed = True
            session.save(update_fields=['redeemed'])
            messages.success(request, f'Gain validé : {session.reward_label}.')
        return redirect('employee-mode')

    if query:
        lookup_code = query.rstrip('/').split('/')[-1] if '/gain/' in query else query
        found_session = GameSession.objects.select_related('customer', 'campaign', 'reward').filter(
            campaign__merchant=merchant
        ).filter(Q(claim_code__iexact=lookup_code) | Q(claim_token__iexact=lookup_code)).order_by('-created_at').first()
        if not found_session:
            messages.error(request, 'Aucun gain trouvé pour ce code ou cette carte.')

    return render(request, 'admin/employee.html', {
        'merchant': merchant,
        'scan_code': query,
        'found_session': found_session,
    })


@login_required
@merchant_unlocked_required
def employee_exit(request):
    merchant = _current_merchant(request)
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        unlock_pin = (request.POST.get('unlock_pin') or '').strip()
        if unlock_pin and merchant and unlock_pin == merchant.employee_pin:
            request.session.pop('growlee_employee_mode', None)
            messages.success(request, 'Mode employeur réouvert par PIN.')
            return redirect('admin-dashboard')
        if form.is_valid():
            user = form.get_user()
            allowed = MerchantMembership.objects.filter(
                user=user,
                merchant=merchant,
                role__in=['owner', 'manager'],
            ).exists()
            if allowed:
                login(request, user)
                request.session.pop('growlee_employee_mode', None)
                messages.success(request, 'Mode employeur réouvert.')
                return redirect('admin-dashboard')
            messages.error(request, 'Ce compte n’a pas les droits employeur pour ce commerce.')
        else:
            messages.error(request, 'Identifiant ou mot de passe incorrect.')
    return render(request, 'admin/employee_exit.html', {'merchant': merchant, 'form': form})


def reward_claim_page(request, token):
    session = get_object_or_404(
        GameSession.objects.select_related('customer', 'campaign__merchant', 'reward'),
        claim_token=token,
    )
    now = timezone.now()
    expired = bool(session.reward_expires_at and session.reward_expires_at < now)
    if request.method == 'POST' and not expired and not session.redeemed:
        session.reward_available_until = now + timedelta(minutes=15)
        session.save(update_fields=['reward_available_until'])
        messages.success(request, 'Votre gain est disponible pendant 15 minutes. Présentez cet écran au point de vente.')
        return redirect('reward-claim-page', token=token)
    return render(request, 'public/reward_claim.html', {
        'session': session,
        'merchant': session.campaign.merchant,
        'expired': expired,
        'window_open': session.is_recovery_window_open,
        'claim_url': reward_claim_url(session),
        'claim_qr': generate_qr_data_uri(reward_claim_url(session), fill_color=session.campaign.merchant.primary_color or '#111827'),
    })


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


def apple_wallet_pass(request, slug):
    session = _latest_session_for_wallet(request, slug)
    wallet_pass = issue_wallet_pass_placeholder(session, 'apple')
    if wallet_pass.status != 'ready':
        return render(request, 'public/wallet_pending.html', {
            'merchant': session.campaign.merchant,
            'provider': 'Apple Wallet',
            'wallet_pass': wallet_pass,
            'config_status': wallet_config_status(),
        }, status=501)
    # Futur branchement: retourner FileResponse(open(pkpass_path, 'rb'), content_type='application/vnd.apple.pkpass')
    return render(request, 'public/wallet_pending.html', {
        'merchant': session.campaign.merchant,
        'provider': 'Apple Wallet',
        'wallet_pass': wallet_pass,
        'config_status': wallet_config_status(),
    })


def google_wallet_pass(request, slug):
    session = _latest_session_for_wallet(request, slug)
    wallet_pass = issue_wallet_pass_placeholder(session, 'google')
    if wallet_pass.status != 'ready' or not wallet_pass.pass_url:
        return render(request, 'public/wallet_pending.html', {
            'merchant': session.campaign.merchant,
            'provider': 'Google Wallet',
            'wallet_pass': wallet_pass,
            'config_status': wallet_config_status(),
        }, status=501)
    return redirect(wallet_pass.pass_url)

def play_page(request, slug):
    merchant = get_object_or_404(Merchant, slug=slug, is_active=True)
    # Le parcours public ne dépend plus uniquement du module Jeu.
    # La campagne courante porte aussi les modules Avis / Wallet et la collecte d'infos.
    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    if campaign is None:
        return render(request, 'public/play.html', {
            'merchant': merchant,
            'campaign': None,
            'entry_point': None,
            'form': ClaimRewardForm(),
            'recent_sessions': [],
            'step': 'inactive',
            'claimed_session': None,
            'wheel_segments': [],
            'total_weight': 0,
            'heading_font_stack': _font_stack(getattr(merchant, 'heading_font', 'inter')),
            'body_font_stack': _font_stack(getattr(merchant, 'body_font', 'inter')),
            'game_step_count': 0,
            'wallet_enabled': False,
        })
    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first()
    game_enabled = bool(campaign.is_active)
    review_enabled = bool(campaign.review_enabled)
    wallet_enabled = bool(campaign.wallet_enabled)
    if game_enabled and campaign.game_type in {'spin', 'scratch'}:
        _ensure_spin_defaults(campaign)
    step = request.GET.get('step', 'landing')
    if step in {'game'} and not game_enabled:
        step = 'landing'
    if step == 'review' and not review_enabled:
        step = 'wallet' if wallet_enabled else 'landing'
    if step == 'wallet' and not wallet_enabled:
        step = 'landing'

    if request.method == 'POST':
        form = ClaimRewardForm(request.POST)
        if form.is_valid():
            customer, session, segment = claim_reward(
                merchant=merchant,
                campaign=campaign,
                phone=form.cleaned_data['phone'],
                email=form.cleaned_data.get('email', ''),
                first_name=form.cleaned_data.get('first_name', ''),
                consent=form.cleaned_data.get('consent', False),
            )
            request.session[f'growlee_last_session_{merchant.slug}'] = session.id
            send_reward_notifications(session)
            next_step = 'reward' if game_enabled else ('review' if review_enabled else ('wallet' if wallet_enabled else 'landing'))
            return redirect(f"/play/{slug}/?step={next_step}")
        step = 'collect'
    else:
        form = ClaimRewardForm()

    session_id = request.session.get(f'growlee_last_session_{merchant.slug}')
    claimed_session = None
    if session_id:
        claimed_session = GameSession.objects.filter(id=session_id, campaign=campaign).select_related('customer', 'reward').first()

    recent_sessions = GameSession.objects.filter(campaign=campaign).select_related('customer').order_by('-created_at')[:5]
    wheel_segments = WheelSegment.objects.filter(campaign=campaign, active=True).select_related('reward').order_by('display_order', 'id')
    total_weight = sum(segment.probability_weight for segment in wheel_segments)
    return render(request, 'public/play.html', {
        'merchant': merchant,
        'campaign': campaign,
        'entry_point': entry_point,
        'form': form,
        'recent_sessions': recent_sessions,
        'step': step,
        'claimed_session': claimed_session,
        'wheel_segments': wheel_segments,
        'total_weight': total_weight,
        'heading_font_stack': _font_stack(getattr(merchant, 'heading_font', 'inter')),
        'body_font_stack': _font_stack(getattr(merchant, 'body_font', 'inter')),
        'game_step_count': 4 if review_enabled and wallet_enabled else (3 if review_enabled or wallet_enabled else 2),
        'game_enabled': game_enabled,
        'review_enabled': review_enabled,
        'wallet_enabled': wallet_enabled,
        'google_review_url': merchant.google_review_url,
    })
