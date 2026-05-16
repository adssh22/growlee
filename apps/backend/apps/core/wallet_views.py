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

