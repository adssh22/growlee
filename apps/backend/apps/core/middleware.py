from urllib.parse import urlencode

from django.shortcuts import redirect

from apps.core.common_views import _control_access_granted, _staff_mfa_for_user


class StaffAdminMfaMiddleware:
    """Require the Growlee Control staff 2FA before Django admin access."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/django-admin/') and request.user.is_authenticated and request.user.is_active and request.user.is_superuser:
            if not _control_access_granted(request):
                mfa = _staff_mfa_for_user(request.user)
                if not mfa.enabled:
                    return redirect('staff-control-mfa-setup')
                querystring = urlencode({'next': request.get_full_path()})
                return redirect(f'/growlee-control/verify/?{querystring}')
        return self.get_response(request)
