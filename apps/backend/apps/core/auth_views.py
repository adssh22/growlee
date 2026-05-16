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

@rate_limit('signup', limit=5, limit_setting='RATELIMIT_SIGNUP_ATTEMPTS', window=3600)
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

@rate_limit('login', limit=8, limit_setting='RATELIMIT_LOGIN_ATTEMPTS', window=900)
def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('staff-merchants')
        return redirect('admin-dashboard')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        next_url = request.GET.get('next') or ''
        if form.get_user().is_superuser and (next_url in {'', '/admin/'}):
            return redirect('staff-merchants')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('admin-dashboard')
    return render(request, 'admin/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('home')

