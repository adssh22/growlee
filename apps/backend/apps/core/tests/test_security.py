from io import BytesIO
from unittest import mock

from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import OperationalError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.accounts.models import MerchantMembership, StaffMFA
from apps.campaigns.models import Campaign, EntryPoint
from apps.customers.forms import ClaimRewardForm
from apps.customers.models import Customer, GameSession
from apps.core.forms import EntryPointForm, MerchantForm
from apps.core.totp import generate_secret
from apps.merchants.models import Merchant, Subscription

TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class ClaimRewardFormConsentTests(TestCase):
    def test_marketing_consent_is_optional_and_false_by_default(self):
        form = ClaimRewardForm(data={'phone': '+33600000000', 'email': 'client@example.test'})

        self.assertTrue(form.is_valid())
        self.assertFalse(form.cleaned_data['consent_marketing'])

    def test_marketing_consent_can_be_checked_explicitly(self):
        form = ClaimRewardForm(data={
            'phone': '+33600000000',
            'email': 'client@example.test',
            'consent_marketing': 'on',
        })

        self.assertTrue(form.is_valid())
        self.assertTrue(form.cleaned_data['consent_marketing'])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SMS_PROVIDER='console')
class PublicPlayConsentTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(name='Play Consent Shop', slug='play-consent-shop', is_active=True)
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='Play Consent Campaign', is_active=True)

    def test_public_claim_without_marketing_consent_still_creates_reward(self):
        response = self.client.post('/play/play-consent-shop/?step=collect', {
            'phone': '+33610000001',
            'email': 'noconsent@example.test',
            'first_name': 'No',
        })

        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(merchant=self.merchant, phone='+33610000001')
        self.assertFalse(customer.consent_marketing)
        self.assertIsNone(customer.consent_marketing_at)
        self.assertTrue(GameSession.objects.filter(customer=customer).exists())

    def test_public_claim_with_marketing_consent_stores_opt_in(self):
        response = self.client.post('/play/play-consent-shop/?step=collect', {
            'phone': '+33610000002',
            'email': 'consent@example.test',
            'first_name': 'Yes',
            'consent_marketing': 'on',
        })

        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(merchant=self.merchant, phone='+33610000002')
        self.assertTrue(customer.consent_marketing)
        self.assertIsNotNone(customer.consent_marketing_at)
        self.assertTrue(GameSession.objects.filter(customer=customer).exists())


class HealthcheckTests(TestCase):
    def test_healthz_returns_ok_when_database_responds(self):
        response = self.client.get('/healthz/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_healthz_returns_503_without_internal_details_when_database_fails(self):
        with mock.patch('apps.core.public_views.connection.cursor', side_effect=OperationalError('secret database detail')):
            response = self.client.get('/healthz/')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unhealthy'})
        self.assertNotIn('secret database detail', response.content.decode())


@override_settings(STORAGES=TEST_STORAGES)
class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(RATELIMIT_LOGIN_ATTEMPTS=2)
    def test_login_is_rate_limited_after_configured_attempts(self):
        for _ in range(2):
            response = self.client.post('/login/', {'username': 'missing', 'password': 'bad'})
            self.assertNotEqual(response.status_code, 429)
        response = self.client.post('/login/', {'username': 'missing', 'password': 'bad'})
        self.assertEqual(response.status_code, 429)


class EmployeePinSecurityTests(TestCase):
    def merchant_form_data(self, name='Pin Shop', pin='123456'):
        return {
            'name': name,
            'primary_color': '#111827',
            'accent_color': '#22c55e',
            'surface_color': '#ffffff',
            'text_color': '#1f2937',
            'heading_font': 'inter',
            'body_font': 'inter',
            'employee_pin': pin,
        }

    def test_merchant_form_requires_six_digit_pin_and_hashes_it(self):
        merchant = Merchant.objects.create(name='Pin Shop', slug='pin-shop')
        form = MerchantForm(data=self.merchant_form_data(), instance=merchant)

        self.assertTrue(form.is_valid(), form.errors)
        merchant = form.save()

        self.assertNotEqual(merchant.employee_pin_hash, '123456')
        self.assertTrue(check_password('123456', merchant.employee_pin_hash))
        self.assertTrue(merchant.check_employee_pin('123456'))

    def test_merchant_form_rejects_short_or_non_digit_pin(self):
        merchant = Merchant.objects.create(name='Pin Shop', slug='pin-shop')
        short_form = MerchantForm(data=self.merchant_form_data(name='Short Pin', pin='12345'), instance=merchant)
        alpha_form = MerchantForm(data=self.merchant_form_data(name='Alpha Pin', pin='12345a'), instance=merchant)

        self.assertFalse(short_form.is_valid())
        self.assertIn('employee_pin', short_form.errors)
        self.assertFalse(alpha_form.is_valid())
        self.assertIn('employee_pin', alpha_form.errors)


@override_settings(STORAGES=TEST_STORAGES)
class StaffAdminMfaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin-2fa', 'admin@example.test', 'secret-12345')
        self.client.force_login(self.user)

    def test_django_admin_redirects_superuser_to_mfa_setup_when_not_enabled(self):
        response = self.client.get('/django-admin/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/growlee-control/mfa/setup/')

    def test_django_admin_redirects_superuser_to_verify_when_mfa_enabled(self):
        StaffMFA.objects.create(user=self.user, secret=generate_secret(), enabled=True)

        response = self.client.get('/django-admin/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/growlee-control/verify/?next=%2Fdjango-admin%2F')

    def test_django_admin_allows_superuser_after_control_mfa_session(self):
        StaffMFA.objects.create(user=self.user, secret=generate_secret(), enabled=True)
        session = self.client.session
        session['growlee_control_2fa_ok'] = True
        session.save()

        response = self.client.get('/django-admin/')

        self.assertEqual(response.status_code, 200)


class QrRedirectSecurityTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(name='QR Shop', slug='qr-shop', is_active=True)
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='QR campaign', is_active=True)

    def test_entry_point_form_allows_relative_redirect(self):
        form = EntryPointForm(data={
            'name': 'Counter',
            'code': 'qr-relative',
            'channel': 'qr',
            'placement': 'counter',
            'redirect_url': '/play/qr-shop/',
        })

        self.assertTrue(form.is_valid(), form.errors)

    @override_settings(QR_REDIRECT_ALLOWED_HOSTS=['allowed.example'])
    def test_entry_point_form_rejects_unsafe_or_external_redirects(self):
        for url in ['javascript:alert(1)', 'data:text/html,hi', 'file:///etc/passwd', 'https://evil.example/path', '//evil.example/path']:
            form = EntryPointForm(data={
                'name': f'Counter {url[:8]}',
                'code': f'qr-{abs(hash(url))}',
                'channel': 'qr',
                'placement': 'counter',
                'redirect_url': url,
            })
            self.assertFalse(form.is_valid(), url)
            self.assertIn('redirect_url', form.errors)

    @override_settings(QR_REDIRECT_ALLOWED_HOSTS=['allowed.example'])
    def test_entry_redirect_allows_only_valid_stored_redirect(self):
        allowed = EntryPoint.objects.create(merchant=self.merchant, campaign=self.campaign, name='Allowed', code='qr-allowed', redirect_url='https://allowed.example/welcome')
        unsafe = EntryPoint.objects.create(merchant=self.merchant, campaign=self.campaign, name='Unsafe', code='qr-unsafe', redirect_url='javascript:alert(1)')

        allowed_response = self.client.get(f'/go/{allowed.code}/')
        unsafe_response = self.client.get(f'/go/{unsafe.code}/')

        self.assertEqual(allowed_response.status_code, 302)
        self.assertEqual(allowed_response['Location'], 'https://allowed.example/welcome')
        self.assertEqual(unsafe_response.status_code, 404)


class UploadValidationTests(TestCase):
    def image_upload(self, name='logo.png', size=(120, 80), fmt='PNG'):
        buf = BytesIO()
        Image.new('RGB', size, '#534ab7').save(buf, format=fmt)
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

    def test_merchant_logo_rejects_non_image_payload(self):
        form = MerchantForm(data={'name': 'Shop'}, files={'logo': SimpleUploadedFile('logo.png', b'not an image', content_type='image/png')})
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)

    def test_merchant_logo_rejects_huge_dimensions(self):
        form = MerchantForm(data={'name': 'Shop'}, files={'logo': self.image_upload(size=(3200, 3200))})
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)


@override_settings(STORAGES=TEST_STORAGES, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MerchantRolePermissionTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(name='Role Shop', slug='role-shop', is_active=True, onboarding_completed=True, onboarding_fee_paid=True, flyer_style='premium', flyer_visual_approved=True)
        Subscription.objects.create(merchant=self.merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='Role Campaign', is_active=True)
        self.owner = User.objects.create_user('role-owner', email='owner@example.test', password='secret-12345')
        self.manager = User.objects.create_user('role-manager', email='manager@example.test', password='secret-12345')
        self.staff = User.objects.create_user('role-staff', email='staff@example.test', password='secret-12345')
        MerchantMembership.objects.create(user=self.owner, merchant=self.merchant, role='owner')
        MerchantMembership.objects.create(user=self.manager, merchant=self.merchant, role='manager')
        MerchantMembership.objects.create(user=self.staff, merchant=self.merchant, role='staff')

    def test_staff_is_redirected_from_full_dashboard_but_can_use_employee_mode(self):
        self.client.force_login(self.staff)

        dashboard_response = self.client.get('/admin/')
        employee_response = self.client.get('/admin/employee/')
        customers_response = self.client.get('/admin/customers/')

        self.assertEqual(dashboard_response.status_code, 302)
        self.assertEqual(dashboard_response['Location'], '/admin/employee/')
        self.assertEqual(employee_response.status_code, 200)
        self.assertEqual(customers_response.status_code, 302)
        self.assertEqual(customers_response['Location'], '/admin/employee/')

    def test_manager_can_manage_campaigns_customers_and_analytics_but_not_billing_or_members(self):
        self.client.force_login(self.manager)

        self.assertEqual(self.client.get('/admin/game/').status_code, 200)
        self.assertEqual(self.client.get('/admin/customers/').status_code, 200)
        self.assertEqual(self.client.get('/admin/analytics/').status_code, 200)
        self.assertEqual(self.client.get('/admin/members/').status_code, 302)
        self.assertEqual(self.client.get('/admin/checkout/').status_code, 302)

    def test_owner_can_add_member_by_email_without_sending_real_invitation(self):
        self.client.force_login(self.owner)

        response = self.client.post('/admin/members/', {'email': 'new-manager@example.test', 'role': 'manager'})

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email='new-manager@example.test')
        membership = MerchantMembership.objects.get(user=user, merchant=self.merchant)
        self.assertEqual(membership.role, 'manager')
        self.assertFalse(user.has_usable_password())


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.merchant_a = Merchant.objects.create(name='A', slug='a', is_active=True, onboarding_completed=True)
        self.merchant_b = Merchant.objects.create(name='B', slug='b', is_active=True, onboarding_completed=True)
        self.user_a = User.objects.create_user('owner-a', password='secret-12345')
        MerchantMembership.objects.create(user=self.user_a, merchant=self.merchant_a, role='owner')
        self.campaign_a = Campaign.objects.create(merchant=self.merchant_a, name='A campaign', is_active=False)
        self.campaign_b = Campaign.objects.create(merchant=self.merchant_b, name='B campaign', is_active=False)
        self.client.force_login(self.user_a)

    def test_toggle_campaign_flag_cannot_modify_other_merchant_campaign(self):
        response = self.client.post('/admin/campaign/toggle/', {
            'campaign_id': self.campaign_b.id,
            'flag': 'is_active',
            'enabled': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.campaign_b.refresh_from_db()
        self.campaign_a.refresh_from_db()
        self.assertFalse(self.campaign_b.is_active)
        # The current user's own campaign may be toggled/fallback-created, but not merchant B.
        self.assertEqual(self.campaign_b.merchant, self.merchant_b)
