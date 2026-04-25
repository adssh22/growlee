import csv
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login, logout
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import MerchantMembership
from apps.campaigns.models import Campaign, EntryPoint, WheelSegment
from apps.core.forms import CampaignForm, EntryPointForm, MerchantForm, RewardForm
from apps.core.utils import build_qr_svg
from apps.customers.forms import ClaimRewardForm
from apps.customers.models import Customer, GameSession, WalletPass
from apps.customers.services import claim_reward
from apps.customers.wallet import build_wallet_payload, issue_wallet_pass_placeholder, wallet_config_status
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


def home(request):
    merchants = Merchant.objects.filter(is_active=True)[:6]
    return render(request, 'public/home.html', {'merchants': merchants})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('admin-dashboard')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect('admin-dashboard')
    return render(request, 'admin/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('home')


def _get_active_campaign_for_merchant(merchant):
    if merchant is None:
        return None
    return Campaign.objects.filter(merchant=merchant, is_active=True).order_by('-created_at', '-id').first()


def _merchant_context_for_user(user):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=user).first()
    merchant = membership.merchant if membership else Merchant.objects.filter(slug='demo-bistro').first()
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
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/dashboard.html', context)


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
        return redirect(f'/admin/setup/?created=1&entry={entry_point.code}')

    context = _merchant_context_for_user(request.user)
    latest_campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    context.update({'merchant_form': merchant_form, 'campaign': latest_campaign})
    return render(request, 'admin/onboarding.html', context)


@login_required
def game_configuration(request):
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    campaign_form = CampaignForm(request.POST or None, instance=campaign, prefix='campaign')
    merchant_style_form = MerchantForm(request.POST or None, request.FILES or None, instance=merchant, prefix='merchant-style')

    if request.method == 'POST':
        action = request.POST.get('form_action')
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

    segments = WheelSegment.objects.filter(campaign=campaign).select_related('reward').order_by('display_order', 'id') if campaign else []
    total_weight = sum(segment.probability_weight for segment in segments if segment.active)
    context.update({'campaign': campaign, 'campaign_form': campaign_form, 'segments': segments, 'total_weight': total_weight, 'merchant_form': merchant_style_form})
    return render(request, 'admin/game_config.html', context)


@login_required
def review_configuration(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/review.html', context)


@login_required
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
def wallet_configuration(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/wallet.html', context)


@login_required
def merchant_setup(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first() if campaign else EntryPoint.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    reward = Reward.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first() if campaign else Reward.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()

    merchant_form = MerchantForm(request.POST or None, instance=merchant, prefix='merchant')
    campaign_form = CampaignForm(request.POST or None, instance=campaign, prefix='campaign')
    entry_form = EntryPointForm(request.POST or None, instance=entry_point, prefix='entry')
    reward_form = RewardForm(request.POST or None, instance=reward, prefix='reward')

    if request.method == 'POST':
        forms_valid = all([
            merchant_form.is_valid(),
            campaign_form.is_valid(),
            entry_form.is_valid(),
            reward_form.is_valid(),
        ])
        if forms_valid:
            merchant = merchant_form.save()
            campaign = campaign_form.save(commit=False)
            campaign.merchant = merchant
            campaign.save()
            entry = entry_form.save(commit=False)
            entry.merchant = merchant
            entry.campaign = campaign
            entry.save()
            reward = reward_form.save(commit=False)
            reward.merchant = merchant
            reward.campaign = campaign
            reward.save()
            messages.success(request, 'Configuration Growlee mise à jour.')
            return redirect('merchant-setup')

    created = request.GET.get('created') == '1'
    qr_entry_code = request.GET.get('entry') or (entry_point.code if entry_point else '')

    return render(request, 'admin/merchant/setup.html', {
        'merchant': merchant,
        'merchant_form': merchant_form,
        'campaign_form': campaign_form,
        'entry_form': entry_form,
        'reward_form': reward_form,
        'created': created,
        'qr_entry_code': qr_entry_code,
    })


@login_required
def qr_preview(request, code):
    entry_point = get_object_or_404(EntryPoint, code=code)
    url = f"{settings.APP_BASE_URL}/play/{entry_point.merchant.slug}/"
    logo_url = entry_point.merchant.logo.url if entry_point.merchant.logo else entry_point.merchant.logo_url
    svg = build_qr_svg(
        data=url,
        merchant_name=entry_point.merchant.name,
        primary_color=entry_point.merchant.primary_color,
        accent_color=entry_point.merchant.accent_color,
        logo_url=logo_url,
    )
    return HttpResponse(svg, content_type='image/svg+xml')


@login_required
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
def rewards_list(request):
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    rewards = Reward.objects.filter(merchant=merchant).order_by('name') if merchant else []
    reward = rewards.first() if rewards else None
    reward_form = RewardForm(request.POST or None, instance=reward, prefix='reward')

    if request.method == 'POST' and merchant and reward_form.is_valid():
        reward = reward_form.save(commit=False)
        reward.merchant = merchant
        reward.campaign = context['campaign']
        reward.save()
        messages.success(request, 'Récompense enregistrée.')
        return redirect('rewards-list')

    context['rewards'] = rewards
    context['reward_form'] = reward_form
    return render(request, 'admin/rewards.html', context)


@login_required
def reward_delete(request, reward_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    reward = get_object_or_404(Reward, id=reward_id, merchant=merchant)
    reward.delete()
    messages.success(request, 'Récompense supprimée.')
    return redirect('rewards-list')


@login_required
def analytics_view(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/analytics.html', context)


@login_required
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
    campaign = _get_active_campaign_for_merchant(merchant)
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
            'game_step_count': 4,
            'wallet_enabled': True,
        })
    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first()
    if campaign.game_type in {'spin', 'scratch'}:
        _ensure_spin_defaults(campaign)
    step = request.GET.get('step', 'landing')
    if step == 'wallet' and not campaign.wallet_enabled:
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
            return redirect(f"/play/{slug}/?step=reward")
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
        'game_step_count': 4 if campaign.review_enabled and campaign.wallet_enabled else (3 if campaign.review_enabled or campaign.wallet_enabled else 2),
        'wallet_enabled': campaign.wallet_enabled,
    })
