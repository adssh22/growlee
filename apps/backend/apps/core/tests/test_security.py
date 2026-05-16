from io import BytesIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import OperationalError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.accounts.models import MerchantMembership
from apps.campaigns.models import Campaign
from apps.core.forms import MerchantForm
from apps.merchants.models import Merchant

TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


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
