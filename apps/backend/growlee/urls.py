from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from django.views.generic.base import RedirectView

from apps.core.auth_views import login_view, logout_view, signup_view
from apps.core.employee_views import employee_exit, employee_mode
from apps.core.merchant_views import (
    admin_dashboard,
    analytics_view,
    automations_view,
    customer_detail,
    customers_export_csv,
    customers_list,
    delete_customer,
    game_configuration,
    merchant_account,
    merchant_checkout,
    merchant_onboarding,
    merchant_setup,
    qr_preview,
    redeem_session,
    reward_delete,
    rewards_list,
    review_configuration,
    toggle_campaign_flag,
)
from apps.core.play_views import entry_redirect, play_page, reward_claim_page
from apps.core.public_views import (
    api_contact,
    contact_page,
    demo_page,
    healthz,
    home,
    legal_page,
    partners_page,
    resources_page,
    robots_txt,
    sitemap_xml,
)
from apps.core.staff_views import staff_control_mfa_setup, staff_control_verify, staff_merchant_detail, staff_merchants
from apps.core.wallet_views import apple_wallet_pass, google_wallet_pass, wallet_configuration, wallet_pass_scan

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('healthz/', healthz, name='healthz'),
    path('', home, name='home'),
    path('demo/', demo_page, name='demo-page'),
    path('ressources/', resources_page, name='resources-page'),
    path('contact/', contact_page, name='contact-page'),
    path('api/contact/', api_contact, name='api-contact'),
    path('partenaires/', partners_page, name='partners-page'),
    path('apporteurs/', partners_page, name='partners-page-apporteurs'),
    path('mentions-legales/', legal_page, {'page': 'mentions-legales'}, name='legal-mentions'),
    path('cgv/', legal_page, {'page': 'cgv'}, name='legal-cgv'),
    path('confidentialite/', legal_page, {'page': 'confidentialite'}, name='legal-privacy'),
    path('robots.txt', robots_txt, name='robots-txt'),
    path('sitemap.xml', sitemap_xml, name='sitemap-xml'),
    path('favicon.ico', RedirectView.as_view(url='/static/brand/favicon.ico', permanent=True), name='favicon'),
    path('login/', login_view, name='login'),
    path('signup/', signup_view, name='signup'),
    path('logout/', logout_view, name='logout'),
    path('growlee-control/mfa/setup/', staff_control_mfa_setup, name='staff-control-mfa-setup'),
    path('growlee-control/verify/', staff_control_verify, name='staff-control-verify'),
    path('_growlee-control/merchants/', staff_merchants, name='staff-merchants'),
    path('growlee-control/merchants/', staff_merchants, name='staff-merchants-alias'),
    path('growlee-control/merchants/<int:merchant_id>/', staff_merchant_detail, name='staff-merchant-detail'),
    path('admin/', admin_dashboard, name='admin-dashboard'),
    path('admin/account/', merchant_account, name='merchant-account'),
    path('admin/checkout/', merchant_checkout, name='merchant-checkout'),
    path('admin/onboarding/', merchant_onboarding, name='merchant-onboarding'),
    path('admin/game/', game_configuration, name='game-configuration'),
    path('admin/game/review/', review_configuration, name='review-configuration'),
    path('admin/game/wallet/', wallet_configuration, name='wallet-configuration'),
    path('admin/wallet/scan/<str:scan_code>/', wallet_pass_scan, name='wallet-pass-scan'),
    path('admin/campaign/toggle/', toggle_campaign_flag, name='toggle-campaign-flag'),
    path('admin/setup/', merchant_setup, name='merchant-setup'),
    path('admin/customers/', customers_list, name='customers-list'),
    path('admin/customers/export/', customers_export_csv, name='customers-export-csv'),
    path('admin/customers/<int:customer_id>/', customer_detail, name='customer-detail'),
    path('admin/customers/<int:customer_id>/delete/', delete_customer, name='customer-delete'),
    path('admin/rewards/', rewards_list, name='rewards-list'),
    path('admin/rewards/<int:reward_id>/delete/', reward_delete, name='reward-delete'),
    path('admin/analytics/', analytics_view, name='analytics-view'),
    path('admin/automations/', automations_view, name='automations-view'),
    path('admin/employee/', employee_mode, name='employee-mode'),
    path('admin/employee/exit/', employee_exit, name='employee-exit'),
    path('admin/sessions/<int:session_id>/redeem/', redeem_session, name='redeem-session'),
    path('gain/<str:token>/', reward_claim_page, name='reward-claim-page'),
    path('admin/qr/<str:code>.svg', qr_preview, name='qr-preview'),
    path('go/<str:code>/', entry_redirect, name='entry-redirect'),
    path('play/<slug:slug>/', play_page, name='play-page'),
    path('play/<slug:slug>/wallet/apple/', apple_wallet_pass, name='apple-wallet-pass'),
    path('play/<slug:slug>/wallet/google/', google_wallet_pass, name='google-wallet-pass'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
