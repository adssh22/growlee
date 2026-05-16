from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.campaigns.models import Campaign
from apps.core.common_views import _merchant_is_unlocked
from apps.customers.models import Customer, GameSession
from apps.core.totp import generate_secret
from apps.merchants.models import Merchant, Subscription
from apps.accounts.models import StaffMFA


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class SubscriptionUnlockTests(TestCase):
    def test_active_subscription_unlocks_active_merchant(self):
        merchant = Merchant.objects.create(name='Active Shop', slug='active-shop', is_active=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)

        self.assertTrue(_merchant_is_unlocked(merchant))

    def test_manual_trialing_subscription_unlocks_active_merchant(self):
        merchant = Merchant.objects.create(name='Trial Shop', slug='trial-shop', is_active=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_TRIALING, provider=Subscription.PROVIDER_MANUAL)

        self.assertTrue(_merchant_is_unlocked(merchant))

    def test_past_due_subscription_blocks_paid_features(self):
        merchant = Merchant.objects.create(name='Late Shop', slug='late-shop', is_active=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_PAST_DUE, provider=Subscription.PROVIDER_MANUAL)

        self.assertFalse(_merchant_is_unlocked(merchant))

    def test_suspended_subscription_blocks_paid_features(self):
        merchant = Merchant.objects.create(name='Suspended Shop', slug='suspended-shop', is_active=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_SUSPENDED, provider=Subscription.PROVIDER_MANUAL)

        self.assertFalse(_merchant_is_unlocked(merchant))

    def test_legacy_active_merchant_without_subscription_still_unlocks_temporarily(self):
        merchant = Merchant.objects.create(name='Legacy Shop', slug='legacy-shop', is_active=True)

        self.assertTrue(_merchant_is_unlocked(merchant))

    def test_inactive_merchant_remains_blocked_even_with_active_subscription(self):
        merchant = Merchant.objects.create(name='Inactive Shop', slug='inactive-shop', is_active=False)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)

        self.assertFalse(_merchant_is_unlocked(merchant))


@override_settings(STORAGES=TEST_STORAGES)
class GrowleeControlSubscriptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('staff', 'staff@example.test', 'secret-12345')
        StaffMFA.objects.create(user=self.user, secret=generate_secret(), enabled=True)
        self.client.force_login(self.user)
        session = self.client.session
        session['growlee_control_2fa_ok'] = True
        session.save()

    def test_control_displays_subscription_status(self):
        merchant = Merchant.objects.create(name='Control Shop', slug='control-shop', is_active=True)
        Subscription.objects.create(
            merchant=merchant,
            plan=Subscription.PLAN_PRO,
            status=Subscription.STATUS_PAST_DUE,
            provider=Subscription.PROVIDER_STRIPE,
            provider_customer_id='cus_future',
            provider_subscription_id='sub_future',
        )

        response = self.client.get('/growlee-control/merchants/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Control Shop')
        self.assertContains(response, 'Past due')
        self.assertContains(response, 'Pro · Stripe')

    def test_direct_billing_action_creates_active_direct_subscription(self):
        merchant = Merchant.objects.create(name='Direct Shop', slug='direct-shop', is_active=False)

        response = self.client.post(f'/growlee-control/merchants/{merchant.id}/', {
            'action': 'activate_direct_billing',
            'billing_reference': 'Facturation directe test',
        })

        self.assertEqual(response.status_code, 302)
        merchant.refresh_from_db()
        subscription = merchant.subscription
        self.assertTrue(merchant.is_active)
        self.assertEqual(subscription.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(subscription.provider, Subscription.PROVIDER_DIRECT)

    def test_control_list_supports_search_and_subscription_filter(self):
        visible = Merchant.objects.create(name='Alpha Bakery', slug='alpha-bakery', is_active=True)
        hidden = Merchant.objects.create(name='Beta Gym', slug='beta-gym', is_active=True)
        Subscription.objects.create(merchant=visible, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        Subscription.objects.create(merchant=hidden, status=Subscription.STATUS_SUSPENDED, provider=Subscription.PROVIDER_MANUAL)

        response = self.client.get('/growlee-control/merchants/?q=alpha&subscription=active')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alpha Bakery')
        self.assertNotContains(response, 'Beta Gym')

    def test_control_list_is_paginated(self):
        for index in range(12):
            merchant = Merchant.objects.create(name=f'Paged Shop {index:02d}', slug=f'paged-shop-{index:02d}', is_active=True)
            Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)

        response = self.client.get('/growlee-control/merchants/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Suivant')
        self.assertEqual(len(response.context['rows']), 10)

    def test_merchant_detail_displays_saas_backoffice_data(self):
        merchant = Merchant.objects.create(name='Detail Shop', slug='detail-shop', is_active=True, is_demo=True)
        Subscription.objects.create(merchant=merchant, plan=Subscription.PLAN_PRO, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        campaign = Campaign.objects.create(merchant=merchant, name='Detail Campaign', is_active=True, review_enabled=True, wallet_enabled=False)
        customer = Customer.objects.create(merchant=merchant, phone='+33633333333', email='detail@example.test', first_name='Ada')
        GameSession.objects.create(customer=customer, campaign=campaign, reward_label='Café offert', is_winner=True)

        response = self.client.get(f'/growlee-control/merchants/{merchant.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Detail Shop')
        self.assertContains(response, 'Ada')
        self.assertContains(response, '+33633333333')
        self.assertContains(response, 'Café offert')
        self.assertContains(response, 'Pro · Manual')
        self.assertContains(response, '2/3')
