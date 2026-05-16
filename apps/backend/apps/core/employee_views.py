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
        if unlock_pin and merchant and merchant.check_employee_pin(unlock_pin):
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

