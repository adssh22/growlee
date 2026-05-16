from apps.core.common_views import *  # noqa: F401,F403
from apps.core.common_views import (  # noqa: F401
    _admin_access_block_response,
    _control_access_granted,
    _current_merchant,
    _employee_mode_block_response,
    _ensure_default_growlee_setup,
    _ensure_spin_defaults,
    _first_membership,
    _font_stack,
    _get_active_campaign_for_merchant,
    _latest_session_for_wallet,
    _merchant_context_for_user,
    _merchant_is_unlocked,
    _merchant_logo_for_svg,
    _pricing_plans,
    _staff_mfa_for_user,
    _staff_mfa_qr_context,
    _unique_merchant_slug,
)

def entry_redirect(request, code):
    entry_point = get_object_or_404(EntryPoint.objects.select_related('merchant'), code=code, merchant__deleted_at__isnull=True, merchant__is_active=True)
    target = entry_point.redirect_url or f'/play/{entry_point.merchant.slug}/'
    return redirect(target)

@rate_limit('reward_claim', limit=20, limit_setting='RATELIMIT_GAIN_ATTEMPTS', window=3600)
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

@rate_limit('play_page', limit=30, limit_setting='RATELIMIT_PLAY_POST_ATTEMPTS', window=3600)
def play_page(request, slug):
    merchant = get_object_or_404(Merchant, slug=slug, is_active=True, deleted_at__isnull=True)
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
                consent_marketing=form.cleaned_data.get('consent_marketing', False),
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

