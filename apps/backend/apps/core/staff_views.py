from apps.core.common_views import *  # noqa: F401,F403
from django.core.paginator import Paginator
from apps.core.audit import log_audit_event
from apps.core.models import AuditLog
from apps.core.common_views import (  # noqa: F401
    _admin_access_block_response,
    _control_access_granted,
    _current_merchant,
    _employee_mode_block_response,
    _ensure_default_growlee_setup,
    _ensure_spin_defaults,
    _ensure_subscription_for_merchant,
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


def _staff_control_gate(request):
    mfa = _staff_mfa_for_user(request.user)
    if not mfa.enabled:
        return redirect('staff-control-mfa-setup')
    if mfa.enabled and not _control_access_granted(request):
        return redirect(f'/growlee-control/verify/?next={request.path}')
    return None


def _run_staff_merchant_action(request, merchant, action):
    if merchant.deleted_at and action != 'restore_merchant':
        messages.error(request, 'Commerce archivé : restaure-le avant toute modification.')
        return False
    if action == 'toggle':
        merchant.is_active = not merchant.is_active
        merchant.save(update_fields=['is_active'])
        subscription = _ensure_subscription_for_merchant(merchant)
        subscription.status = Subscription.STATUS_ACTIVE if merchant.is_active else Subscription.STATUS_SUSPENDED
        subscription.save(update_fields=['status', 'updated_at'])
        log_audit_event(request, 'staff.merchant.toggle_active', target=merchant, merchant=merchant, metadata={'is_active': merchant.is_active})
        messages.success(request, f'{merchant.name} est maintenant {"actif" if merchant.is_active else "désactivé"}.')
        return True
    if action == 'toggle_demo':
        merchant.is_demo = not merchant.is_demo
        merchant.demo_expires_at = timezone.now() + timedelta(days=14) if merchant.is_demo else None
        merchant.is_active = True if merchant.is_demo else merchant.is_active
        merchant.save(update_fields=['is_demo', 'demo_expires_at', 'is_active'])
        subscription = _ensure_subscription_for_merchant(merchant)
        if merchant.is_demo and subscription.status not in Subscription.UNLOCKED_STATUSES:
            subscription.status = Subscription.STATUS_TRIALING
            subscription.save(update_fields=['status', 'updated_at'])
        log_audit_event(request, 'staff.merchant.toggle_demo', target=merchant, merchant=merchant, metadata={'is_demo': merchant.is_demo, 'demo_expires_at': merchant.demo_expires_at.isoformat() if merchant.demo_expires_at else None})
        messages.success(request, f'Accès démo {"activé" if merchant.is_demo else "désactivé"} pour {merchant.name}.')
        return True
    if action == 'activate_direct_billing':
        merchant.is_active = True
        merchant.is_demo = False
        merchant.demo_expires_at = None
        merchant.onboarding_fee_paid = True
        merchant.onboarding_completed = True
        merchant.flyer_visual_approved = True
        merchant.flyer_order_status = 'visual_approved_waiting_payment'
        if not merchant.flyer_style:
            merchant.flyer_style = 'premium'
        merchant.payment_method = 'Facturation directe'
        merchant.billing_payment_type = 'direct'
        merchant.billing_payment_reference = (request.POST.get('billing_reference') or '').strip()[:120] or 'Activation manuelle staff'
        merchant.save(update_fields=['is_active', 'is_demo', 'demo_expires_at', 'onboarding_fee_paid', 'onboarding_completed', 'flyer_visual_approved', 'flyer_order_status', 'flyer_style', 'payment_method', 'billing_payment_type', 'billing_payment_reference'])
        subscription = _ensure_subscription_for_merchant(merchant, provider=Subscription.PROVIDER_DIRECT, status=Subscription.STATUS_ACTIVE)
        subscription.provider = Subscription.PROVIDER_DIRECT
        subscription.status = Subscription.STATUS_ACTIVE
        subscription.save(update_fields=['provider', 'status', 'updated_at'])
        campaign, _, _ = _ensure_default_growlee_setup(merchant)
        campaign.is_active = True
        campaign.review_enabled = True
        campaign.wallet_enabled = True
        campaign.save(update_fields=['is_active', 'review_enabled', 'wallet_enabled'])
        log_audit_event(request, 'staff.billing.activate_direct', target=merchant, merchant=merchant, metadata={'subscription_provider': subscription.provider, 'subscription_status': subscription.status, 'billing_reference': merchant.billing_payment_reference})
        messages.success(request, f'{merchant.name} est activé en facturation directe. Le commerçant peut accéder à son compte sans paiement via le site.')
        return True
    if action == 'module_toggle':
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
        log_audit_event(request, 'staff.campaign.module_toggle', target=campaign, merchant=merchant, metadata={'flag': flag, 'is_active': campaign.is_active, 'review_enabled': campaign.review_enabled, 'wallet_enabled': campaign.wallet_enabled})
        messages.success(request, f'Module mis à jour pour {merchant.name}.')
        return True
    if action == 'archive_merchant':
        confirm = (request.POST.get('confirm_name') or '').strip()
        if confirm != merchant.name:
            messages.error(request, f'Archivage annulé : tape exactement le nom du commerce ({merchant.name}).')
            return False
        merchant.is_active = False
        merchant.is_demo = False
        merchant.demo_expires_at = None
        merchant.deleted_at = timezone.now()
        merchant.deleted_by = request.user if request.user.is_authenticated else None
        merchant.save(update_fields=['is_active', 'is_demo', 'demo_expires_at', 'deleted_at', 'deleted_by'])
        subscription = _ensure_subscription_for_merchant(merchant)
        subscription.status = Subscription.STATUS_SUSPENDED
        subscription.save(update_fields=['status', 'updated_at'])
        log_audit_event(request, 'staff.merchant.archive', target=merchant, merchant=merchant, metadata={'merchant_name': merchant.name, 'merchant_slug': merchant.slug})
        messages.success(request, f'Commerce archivé : {merchant.name}. Les données, users, stats et sessions sont conservés.')
        return True
    if action == 'restore_merchant':
        if not merchant.deleted_at:
            messages.info(request, f'{merchant.name} n’est pas archivé.')
            return False
        merchant.deleted_at = None
        merchant.deleted_by = None
        merchant.is_active = True
        merchant.save(update_fields=['deleted_at', 'deleted_by', 'is_active'])
        subscription = _ensure_subscription_for_merchant(merchant)
        if subscription.status in {Subscription.STATUS_SUSPENDED, Subscription.STATUS_CANCELED}:
            subscription.status = Subscription.STATUS_ACTIVE
            subscription.save(update_fields=['status', 'updated_at'])
        log_audit_event(request, 'staff.merchant.restore', target=merchant, merchant=merchant, metadata={'merchant_name': merchant.name, 'merchant_slug': merchant.slug})
        messages.success(request, f'Commerce restauré : {merchant.name}.')
        return True
    return False

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
            next_url = request.GET.get('next') or ''
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('staff-merchants')
        error = 'Code 2FA invalide.'

    return render(request, 'admin/staff_control_verify.html', {'error': error})

@superuser_required
def staff_merchants(request):
    mfa = _staff_mfa_for_user(request.user)
    gated = _staff_control_gate(request)
    if gated is not None:
        return gated

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
            log_audit_event(request, 'staff.mfa.reset', target=target_user, metadata={'target_username': target_user.username})
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
        if action in {'toggle', 'toggle_demo', 'activate_direct_billing', 'archive_merchant', 'restore_merchant', 'module_toggle'}:
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            handled = _run_staff_merchant_action(request, merchant, action)
            if action == 'archive_merchant' and handled:
                return redirect('staff-merchants')
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
                _ensure_subscription_for_merchant(merchant)
                _ensure_default_growlee_setup(merchant)
            messages.success(request, f'Commerce créé : {merchant.name}. Propriétaire : {user.username}')
            return redirect('staff-merchants')

    merchants = Merchant.objects.select_related('subscription').prefetch_related('memberships__user').order_by('-created_at')
    all_merchants = merchants.filter(deleted_at__isnull=True)
    q = (request.GET.get('q') or '').strip()
    active_filter = request.GET.get('active') or ''
    demo_filter = request.GET.get('demo') or ''
    subscription_filter = request.GET.get('subscription') or ''
    archived_filter = request.GET.get('archived') or ''
    if archived_filter == 'yes':
        merchants = merchants.filter(deleted_at__isnull=False)
    else:
        merchants = merchants.filter(deleted_at__isnull=True)
    if q:
        merchants = merchants.filter(Q(name__icontains=q) | Q(slug__icontains=q) | Q(contact_email__icontains=q) | Q(memberships__user__email__icontains=q) | Q(memberships__user__username__icontains=q)).distinct()
    if active_filter == 'active':
        merchants = merchants.filter(is_active=True)
    elif active_filter == 'inactive':
        merchants = merchants.filter(is_active=False)
    if demo_filter == 'yes':
        merchants = merchants.filter(is_demo=True)
    elif demo_filter == 'no':
        merchants = merchants.filter(is_demo=False)
    if subscription_filter == 'active':
        merchants = merchants.filter(subscription__status__in=[Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING])
    elif subscription_filter == 'suspended':
        merchants = merchants.filter(subscription__status__in=[Subscription.STATUS_PAST_DUE, Subscription.STATUS_SUSPENDED, Subscription.STATUS_CANCELED])

    paginator = Paginator(merchants, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    rows = []
    for merchant in page_obj.object_list:
        campaigns = Campaign.objects.filter(merchant=merchant)
        subscription = _ensure_subscription_for_merchant(merchant)
        rows.append({
            'merchant': merchant,
            'subscription': subscription,
            'owners': [m for m in merchant.memberships.all() if m.role == 'owner'],
            'campaigns_count': campaigns.count(),
            'customers_count': Customer.objects.filter(merchant=merchant).count(),
            'active_campaign': campaigns.order_by('-created_at', '-id').first(),
        })
    query_params = request.GET.copy()
    query_params.pop('page', None)
    mfa_context = _staff_mfa_qr_context(request.user, mfa)
    staff_mfa_users = User.objects.filter(is_active=True, is_superuser=True).order_by('username')
    return render(request, 'admin/staff_merchants.html', {
        'form': form,
        'rows': rows,
        'page_obj': page_obj,
        'querystring': query_params.urlencode(),
        'filters': {'q': q, 'active': active_filter, 'demo': demo_filter, 'subscription': subscription_filter, 'archived': archived_filter},
        'staff_mfa_users': staff_mfa_users,
        'total_merchants': all_merchants.count(),
        'active_merchants': all_merchants.filter(is_active=True).count(),
        'filtered_merchants': merchants.count(),
        'total_users': User.objects.count(),
        'mfa_error': mfa_error,
        **mfa_context,
    })


@superuser_required
def staff_merchant_detail(request, merchant_id):
    gated = _staff_control_gate(request)
    if gated is not None:
        return gated

    merchant = get_object_or_404(Merchant.objects.prefetch_related('memberships__user'), id=merchant_id)
    subscription = _ensure_subscription_for_merchant(merchant)

    if request.method == 'POST':
        action = request.POST.get('action')
        handled = _run_staff_merchant_action(request, merchant, action)
        if action == 'archive_merchant' and handled:
            return redirect('staff-merchants')
        return redirect('staff-merchant-detail', merchant_id=merchant.id)

    campaigns = Campaign.objects.filter(merchant=merchant)
    active_campaign = campaigns.order_by('-created_at', '-id').first()
    customers = Customer.objects.filter(merchant=merchant).order_by('-created_at')
    sessions = GameSession.objects.filter(campaign__merchant=merchant).select_related('customer', 'campaign', 'reward').order_by('-created_at')
    owners = [membership for membership in merchant.memberships.all() if membership.role == 'owner']
    modules = {
        'game': bool(active_campaign and active_campaign.is_active),
        'review': bool(active_campaign and active_campaign.review_enabled),
        'wallet': bool(active_campaign and active_campaign.wallet_enabled),
    }

    return render(request, 'admin/staff_merchant_detail.html', {
        'merchant': merchant,
        'subscription': subscription,
        'owners': owners,
        'customers_count': customers.count(),
        'sessions_count': sessions.count(),
        'latest_customers': customers[:8],
        'latest_sessions': sessions[:8],
        'campaigns_count': campaigns.count(),
        'active_campaign': active_campaign,
        'modules': modules,
        'active_modules_count': int(modules['game']) + int(modules['review']) + int(modules['wallet']),
        'latest_audit_logs': AuditLog.objects.select_related('actor').filter(merchant=merchant).order_by('-created_at')[:10],
    })


@superuser_required
def staff_support(request):
    gated = _staff_control_gate(request)
    if gated is not None:
        return gated

    q = (request.GET.get('q') or '').strip()
    results = {
        'merchants': [],
        'customers': [],
        'sessions': [],
        'entry_points': [],
    }
    if q:
        log_audit_event(request, 'staff.support.search', metadata={'query': q[:120]})
        results['merchants'] = list(
            Merchant.objects.filter(
                Q(name__icontains=q) |
                Q(slug__icontains=q) |
                Q(contact_email__icontains=q) |
                Q(memberships__user__email__icontains=q) |
                Q(memberships__user__username__icontains=q)
            ).distinct().order_by('name')[:20]
        )
        results['customers'] = list(
            Customer.objects.select_related('merchant').filter(
                Q(phone__icontains=q) |
                Q(email__icontains=q) |
                Q(first_name__icontains=q)
            ).order_by('-created_at')[:20]
        )
        results['sessions'] = list(
            GameSession.objects.select_related('customer', 'campaign__merchant', 'reward').filter(
                Q(claim_code__iexact=q) |
                Q(claim_token__iexact=q)
            ).order_by('-created_at')[:20]
        )
        results['entry_points'] = list(
            EntryPoint.objects.select_related('merchant', 'campaign').filter(code__icontains=q).order_by('code')[:20]
        )

    return render(request, 'admin/staff_support.html', {
        'q': q,
        'results': results,
    })
