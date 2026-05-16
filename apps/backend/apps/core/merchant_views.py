import stripe
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Prefetch, Subquery

from apps.core.common_views import *  # noqa: F401,F403
from apps.core.audit import log_audit_event
from apps.core.billing import stripe_configured
from apps.core.common_views import (  # noqa: F401
    _admin_access_block_response,
    _control_access_granted,
    _current_merchant,
    can_manage_billing,
    can_manage_campaigns,
    can_manage_customers,
    current_membership,
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
    merchant_role_required,
    _staff_mfa_for_user,
    _staff_mfa_qr_context,
    _unique_merchant_slug,
)

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

@login_required
@merchant_role_required(can_manage_billing)
def merchant_checkout(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')
    if stripe_configured():
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode='subscription',
            customer_email=merchant.contact_email or request.user.email or None,
            client_reference_id=str(merchant.id),
            line_items=[{'price': settings.STRIPE_PRICE_ID_PRO, 'quantity': 1}],
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
            metadata={'merchant_id': str(merchant.id)},
            subscription_data={'metadata': {'merchant_id': str(merchant.id)}},
        )
        log_audit_event(request, 'billing.stripe.checkout_created', target=merchant, merchant=merchant, metadata={'stripe_session_id': session.id})
        return redirect(session.url)

    payment_link = settings.GROWLEE_PAYMENT_LINK_PRO
    if payment_link:
        return redirect(payment_link)
    messages.info(request, 'Checkout Growlee prêt : configurez Stripe ou GROWLEE_PAYMENT_LINK_PRO pour activer le paiement.')
    return render(request, 'admin/pending_payment.html', {'merchant': merchant, 'pricing_plans': _pricing_plans()})

@login_required
@merchant_role_required(can_manage_billing)
def merchant_onboarding(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')
    if request.method == 'GET' and request.path == '/admin/onboarding/' and merchant.onboarding_completed:
        context = _merchant_context_for_user(request.user)
        if context.get('campaign') is None:
            _ensure_default_growlee_setup(merchant)
            context = _merchant_context_for_user(request.user)
        return render(request, 'admin/configuration.html', context)
    merchant_form = MerchantForm(
        request.POST or None,
        request.FILES or None,
        instance=merchant,
        prefix='merchant',
    )
    if request.method == 'POST' and request.POST.get('form_action') == 'flyer_approve':
        if not merchant.onboarding_completed:
            messages.error(request, 'Complétez d’abord les informations commerce avant de valider le flyer.')
            return redirect('merchant-account')
        merchant.flyer_visual_approved = True
        merchant.flyer_order_status = 'visual_approved_waiting_payment'
        merchant.save(update_fields=['flyer_visual_approved', 'flyer_order_status'])
        messages.success(request, 'Visuel flyer validé. Il reste le paiement onboarding de 80€ pour débloquer l’application et lancer la commande.')
        return redirect('merchant-account')

    if request.method == 'POST' and request.POST.get('form_action') == 'merchant_identity' and merchant_form.is_valid():
        merchant = merchant_form.save(commit=False)
        if merchant.billing_payment_type and not merchant.payment_method:
            merchant.payment_method = 'Carte bancaire' if merchant.billing_payment_type == 'cb' else 'IBAN / prélèvement'
        required = {
            'Nom': merchant.name,
            'Adresse': merchant.address,
            'Secteur d’activité': merchant.business_sector,
            'Email de contact': merchant.contact_email,
            'Offre flyers': merchant.flyer_offer,
        }
        missing = [label for label, value in required.items() if not (value or '').strip()]
        if missing:
            messages.error(request, 'Champs obligatoires manquants : ' + ', '.join(missing) + '.')
            return redirect('merchant-account')
        if not merchant.flyer_style:
            merchant.flyer_style = 'premium'
        merchant.onboarding_completed = True
        merchant.flyer_visual_approved = True
        merchant.flyer_order_status = 'visual_approved_waiting_payment'
        merchant.save()
        merchant_form.save_m2m()
        campaign, entry_point, reward = _ensure_default_growlee_setup(merchant)
        if merchant.is_active:
            messages.success(request, 'Onboarding enregistré. Votre dashboard, votre QR code et votre parcours client personnalisé sont prêts.')
            return redirect('admin-dashboard')
        messages.success(request, 'Onboarding enregistré. Vos informations sont sauvegardées : vous pouvez revenir payer ou demander une activation par facturation directe plus tard.')
        return redirect('merchant-account')

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
            return redirect('merchant-account')
        if qr_entry:
            logo_url = _merchant_logo_for_svg(merchant)
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

merchant_account = merchant_onboarding


@login_required
@merchant_role_required(can_manage_billing)
def merchant_members(request):
    membership = current_membership(request)
    merchant = membership.merchant if membership else None
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()
        role = (request.POST.get('role') or 'staff').strip()
        if role not in {'manager', 'staff'}:
            messages.error(request, 'Rôle invalide. Un owner ne peut pas être créé depuis cette page.')
            return redirect('merchant-members')
        if not email:
            messages.error(request, 'Email obligatoire.')
            return redirect('merchant-members')
        user = User.objects.filter(email__iexact=email).first()
        created_user = False
        if user is None:
            base_username = slugify(email.split('@')[0]) or 'membre'
            username = base_username[:120]
            counter = 2
            while User.objects.filter(username=username).exists():
                suffix = f'-{counter}'
                username = f'{base_username[:120-len(suffix)]}{suffix}'
                counter += 1
            user = User(username=username, email=email, is_active=True)
            user.set_unusable_password()
            user.save()
            created_user = True
        membership_obj, created_membership = MerchantMembership.objects.update_or_create(
            user=user,
            merchant=merchant,
            defaults={'role': role},
        )
        log_audit_event(request, 'merchant.member.upsert', target=membership_obj, merchant=merchant, metadata={'email': email, 'role': role, 'created_user': created_user, 'created_membership': created_membership})
        messages.success(request, f'Membre {"créé" if created_membership else "mis à jour"} : {email} · {role}. Aucun email réel envoyé automatiquement.')
        return redirect('merchant-members')
    members = MerchantMembership.objects.select_related('user').filter(merchant=merchant).order_by('role', 'user__email', 'user__username')
    return render(request, 'admin/members.html', {'merchant': merchant, 'members': members})


@login_required
@merchant_role_required(can_manage_campaigns)
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
            log_audit_event(request, 'merchant.campaign.update', target=campaign, merchant=merchant, metadata={'game_type': campaign.game_type, 'is_active': campaign.is_active, 'review_enabled': campaign.review_enabled, 'wallet_enabled': campaign.wallet_enabled})
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
@merchant_role_required(can_manage_campaigns)
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
@merchant_role_required(can_manage_campaigns)
def toggle_campaign_flag(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    campaign = context['campaign']
    if campaign is None and merchant:
        campaign, _entry_point, _reward = _ensure_default_growlee_setup(merchant)
    campaign_id = request.POST.get('campaign_id')
    if campaign_id and merchant:
        campaign = Campaign.objects.filter(id=campaign_id, merchant=merchant).first() or campaign
    if campaign is None:
        messages.error(request, 'Aucune campagne à modifier.')
        return redirect('merchant-onboarding')
    flag = request.POST.get('flag')
    requested = request.POST.get('value')
    desired = (requested == '1') if requested in {'0', '1'} else None
    labels = {
        'is_active': 'Jeu',
        'review_enabled': 'Avis',
        'wallet_enabled': 'Wallet',
    }
    if flag in labels:
        current = getattr(campaign, flag)
        next_value = desired if desired is not None else (not current)
        setattr(campaign, flag, next_value)
        campaign.save(update_fields=[flag])
        log_audit_event(request, 'merchant.campaign.module_toggle', target=campaign, merchant=merchant, metadata={'flag': flag, 'enabled': next_value})
        messages.success(request, f'Module {labels[flag]} {"activé" if next_value else "désactivé"}.')
    else:
        messages.error(request, 'Option inconnue.')
    return redirect(request.POST.get('next') or 'merchant-onboarding')

@login_required
@merchant_role_required(can_manage_campaigns)
def merchant_setup(request):
    """Legacy QR setup route kept for existing dashboard links.

    The QR setup screen was merged into the main game configuration page, which
    now owns campaign, reward and entry-point setup. Keep /admin/setup/
    functional as a narrow compatibility redirect without unreachable code.
    """
    return redirect('game-configuration')

@login_required
def qr_preview(request, code):
    entry_point = get_object_or_404(EntryPoint.objects.select_related('merchant'), code=code)
    if not request.user.is_superuser and not MerchantMembership.objects.filter(user=request.user, merchant=entry_point.merchant, role__in=['owner', 'manager']).exists():
        messages.error(request, 'Accès QR réservé aux responsables du commerce.')
        return redirect('admin-dashboard')
    url = f"{settings.APP_BASE_URL}/go/{entry_point.code}/"
    logo_url = _merchant_logo_for_svg(entry_point.merchant)
    svg = build_qr_svg(
        data=url,
        merchant_name=entry_point.merchant.name,
        primary_color=entry_point.merchant.primary_color,
        accent_color=entry_point.merchant.accent_color,
        logo_url=logo_url,
    )
    return HttpResponse(svg, content_type='image/svg+xml')

@login_required
@merchant_role_required(can_manage_customers)
def customers_list(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    query = (request.GET.get('q') or '').strip()
    latest_session_ids = GameSession.objects.filter(customer=OuterRef('pk')).order_by('-created_at', '-id').values('id')[:1]
    customers = (
        Customer.objects.filter(merchant=merchant, deleted_at__isnull=True)
        .annotate(sessions_count=Count('game_sessions'), latest_session_id=Subquery(latest_session_ids))
        .prefetch_related(
            Prefetch(
                'game_sessions',
                queryset=GameSession.objects.select_related('reward').order_by('-created_at', '-id'),
                to_attr='prefetched_sessions',
            )
        )
        .order_by('-created_at')
    )
    if query:
        customers = customers.filter(
            Q(phone__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query)
        )
    paginator = Paginator(customers, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    for customer in page_obj.object_list:
        customer.latest_session = customer.prefetched_sessions[0] if customer.prefetched_sessions else None
    query_params = request.GET.copy()
    query_params.pop('page', None)
    return render(request, 'admin/customers.html', {
        'merchant': merchant,
        'customers': page_obj.object_list,
        'page_obj': page_obj,
        'querystring': query_params.urlencode(),
        'query': query,
    })

@login_required
@merchant_role_required(can_manage_customers)
def customer_detail(request, customer_id):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    customer = get_object_or_404(Customer, id=customer_id, merchant=merchant, deleted_at__isnull=True)
    sessions = customer.game_sessions.select_related('campaign', 'reward').order_by('-created_at')
    return render(request, 'admin/customer_detail.html', {
        'customer': customer,
        'sessions': sessions,
    })

@login_required
@merchant_role_required(can_manage_customers)
def delete_customer(request, customer_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    customer = get_object_or_404(Customer, id=customer_id, merchant=merchant, deleted_at__isnull=True)
    phone = customer.phone
    customer.deleted_at = timezone.now()
    customer.deleted_by = request.user if request.user.is_authenticated else None
    customer.save(update_fields=['deleted_at', 'deleted_by'])
    log_audit_event(request, 'merchant.customer.archive', target=customer, merchant=merchant, metadata={'phone': phone})
    messages.success(request, f'Client archivé: {phone}.')
    return redirect('customers-list')

@login_required
@merchant_role_required(can_manage_customers)
def customers_export_csv(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        return redirect('admin-dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="growlee-customers-{merchant.slug}.csv"'
    writer = csv.writer(response)
    writer.writerow(['phone', 'first_name', 'email', 'created_at', 'sessions_count'])
    customers = (
        Customer.objects.filter(merchant=merchant, deleted_at__isnull=True)
        .annotate(sessions_count=Count('game_sessions'))
        .order_by('-created_at')
    )
    for customer in customers:
        writer.writerow([
            customer.phone,
            customer.first_name,
            customer.email,
            customer.created_at.isoformat(),
            customer.sessions_count,
        ])
    return response

@login_required
@merchant_role_required(can_manage_campaigns)
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
@merchant_role_required(can_manage_campaigns)
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
@merchant_role_required(lambda membership: bool(membership and membership.role in {'owner', 'manager'}))
def analytics_view(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/analytics.html', context)

@login_required
@merchant_role_required(can_manage_campaigns)
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
@merchant_role_required(can_manage_customers)
def redeem_session(request, session_id):
    if request.method != 'POST':
        return redirect('admin-dashboard')
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    session = get_object_or_404(GameSession.objects.select_related('customer', 'campaign'), id=session_id, customer__merchant=merchant)
    if not session.redeemed:
        session.redeemed = True
        session.save(update_fields=['redeemed'])
        log_audit_event(request, 'merchant.session.redeem', target=session, merchant=merchant, metadata={'customer_id': session.customer_id, 'reward_label': session.reward_label})
        messages.success(request, f'Gain marqué comme utilisé pour {session.customer.phone}.')
    return redirect('customer-detail', customer_id=session.customer_id)

