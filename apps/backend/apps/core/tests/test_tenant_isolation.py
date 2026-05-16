from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import MerchantMembership
from apps.campaigns.models import Campaign, EntryPoint
from apps.customers.models import Customer, GameSession
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=TEST_STORAGES)
class MerchantTenantIsolationTests(TestCase):
    def setUp(self):
        self.merchant_a = self._merchant('Commerce A', 'commerce-a')
        self.merchant_b = self._merchant('Commerce B', 'commerce-b')
        self.user_a = User.objects.create_user('owner-a-isolation', password='pass1234')
        self.user_b = User.objects.create_user('owner-b-isolation', password='pass1234')
        MerchantMembership.objects.create(user=self.user_a, merchant=self.merchant_a, role='owner')
        MerchantMembership.objects.create(user=self.user_b, merchant=self.merchant_b, role='owner')

        self.campaign_a = Campaign.objects.create(merchant=self.merchant_a, name='Campaign A', is_active=True)
        self.campaign_b = Campaign.objects.create(merchant=self.merchant_b, name='Campaign B Secret', is_active=True)
        self.entry_a = EntryPoint.objects.create(merchant=self.merchant_a, campaign=self.campaign_a, name='QR A', code='qr-a')
        self.entry_b = EntryPoint.objects.create(merchant=self.merchant_b, campaign=self.campaign_b, name='QR B', code='qr-b-secret')
        self.reward_a = Reward.objects.create(merchant=self.merchant_a, campaign=self.campaign_a, name='Reward A', description='Reward A visible')
        self.reward_b = Reward.objects.create(merchant=self.merchant_b, campaign=self.campaign_b, name='Reward B Secret', description='Reward B hidden')
        self.customer_a = Customer.objects.create(merchant=self.merchant_a, phone='+33111111111', first_name='Alice A', email='a@example.test')
        self.customer_b = Customer.objects.create(merchant=self.merchant_b, phone='+33222222222', first_name='Bob B Secret', email='b@example.test')
        self.session_a = GameSession.objects.create(
            customer=self.customer_a,
            campaign=self.campaign_a,
            reward=self.reward_a,
            reward_label='Reward A visible',
            claim_token='token-a',
            is_winner=True,
        )
        self.session_b = GameSession.objects.create(
            customer=self.customer_b,
            campaign=self.campaign_b,
            reward=self.reward_b,
            reward_label='Reward B hidden',
            claim_token='token-b',
            is_winner=True,
        )
        self.client.force_login(self.user_a)

    def _merchant(self, name, slug):
        return Merchant.objects.create(
            name=name,
            slug=slug,
            is_active=True,
            onboarding_completed=True,
            onboarding_fee_paid=True,
            flyer_style='premium',
            flyer_visual_approved=True,
        )

    def assert_not_leaking_merchant_b(self, response):
        self.assertNotContains(response, 'Commerce B')
        self.assertNotContains(response, 'Campaign B Secret')
        self.assertNotContains(response, 'Reward B Secret')
        self.assertNotContains(response, 'Reward B hidden')
        self.assertNotContains(response, 'Bob B Secret')
        self.assertNotContains(response, '+33222222222')
        self.assertNotContains(response, 'b@example.test')

    def test_customers_list_only_shows_current_merchant_customers(self):
        response = self.client.get('/admin/customers/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alice A')
        self.assertContains(response, '+33111111111')
        self.assert_not_leaking_merchant_b(response)

    def test_customer_detail_rejects_other_merchant_customer(self):
        own_response = self.client.get(f'/admin/customers/{self.customer_a.id}/')
        other_response = self.client.get(f'/admin/customers/{self.customer_b.id}/')

        self.assertEqual(own_response.status_code, 200)
        self.assertContains(own_response, 'Alice A')
        self.assertEqual(other_response.status_code, 404)

    def test_delete_customer_cannot_delete_other_merchant_customer(self):
        response = self.client.post(f'/admin/customers/{self.customer_b.id}/delete/')

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Customer.objects.filter(pk=self.customer_b.pk, merchant=self.merchant_b).exists())

    def test_game_configuration_rewards_are_scoped_to_current_merchant(self):
        response = self.client.get('/admin/game/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reward A')
        self.assert_not_leaking_merchant_b(response)

    def test_reward_delete_cannot_delete_other_merchant_reward(self):
        response = self.client.post(f'/admin/rewards/{self.reward_b.id}/delete/')

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Reward.objects.filter(pk=self.reward_b.pk, merchant=self.merchant_b).exists())

    def test_dashboard_is_scoped_to_current_merchant_activity(self):
        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alice A')
        self.assertContains(response, 'Campaign A')
        self.assert_not_leaking_merchant_b(response)

    def test_qr_preview_rejects_other_merchant_entry_point(self):
        own_response = self.client.get(f'/admin/qr/{self.entry_a.code}.svg')
        other_response = self.client.get(f'/admin/qr/{self.entry_b.code}.svg')

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(own_response['Content-Type'], 'image/svg+xml')
        self.assertEqual(other_response.status_code, 302)
        self.assertEqual(other_response['Location'], '/admin/')
