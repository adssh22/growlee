from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.campaigns.models import Campaign
from apps.core.common_views import _merchant_is_unlocked
from apps.customers.models import Customer, GameSession
from apps.core.models import AuditLog
from apps.core.totp import generate_secret
from apps.merchants.models import Merchant, Subscription
from apps.accounts.models import MerchantMembership, StaffMFA


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
        self.assertTrue(AuditLog.objects.filter(action='staff.billing.activate_direct', merchant=merchant).exists())

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
        AuditLog.objects.create(actor=self.user, merchant=merchant, action='staff.merchant.toggle_demo', target_type='Merchant', target_id=str(merchant.id), metadata={'is_demo': True})

        response = self.client.get(f'/growlee-control/merchants/{merchant.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Detail Shop')
        self.assertContains(response, 'Ada')
        self.assertContains(response, '+33633333333')
        self.assertContains(response, 'Café offert')
        self.assertContains(response, 'Pro · Manual')
        self.assertContains(response, '2/3')
        self.assertContains(response, 'staff.merchant.toggle_demo')

    def test_staff_toggle_active_demo_and_module_create_audit_logs(self):
        merchant = Merchant.objects.create(name='Staff Audit Shop', slug='staff-audit-shop', is_active=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        Campaign.objects.create(merchant=merchant, name='Staff Audit Campaign', is_active=True)

        self.client.post(f'/growlee-control/merchants/{merchant.id}/', {'action': 'toggle'})
        self.client.post(f'/growlee-control/merchants/{merchant.id}/', {'action': 'toggle_demo'})
        self.client.post(f'/growlee-control/merchants/{merchant.id}/', {'action': 'module_toggle', 'flag': 'game'})

        self.assertTrue(AuditLog.objects.filter(action='staff.merchant.toggle_active', merchant=merchant).exists())
        self.assertTrue(AuditLog.objects.filter(action='staff.merchant.toggle_demo', merchant=merchant).exists())
        self.assertTrue(AuditLog.objects.filter(action='staff.campaign.module_toggle', merchant=merchant).exists())

    def test_staff_reset_mfa_creates_audit_log(self):
        other_staff = User.objects.create_superuser('other-staff', 'other@example.test', 'secret-12345')
        StaffMFA.objects.create(user=other_staff, secret=generate_secret(), enabled=True)

        response = self.client.post('/growlee-control/merchants/', {'action': 'reset_staff_mfa', 'user_id': other_staff.id})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action='staff.mfa.reset', actor=self.user, target_type='User', target_id=str(other_staff.id)).exists())

    def test_staff_delete_merchant_creates_audit_log(self):
        merchant = Merchant.objects.create(name='Delete Audit Shop', slug='delete-audit-shop', is_active=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        merchant_id = merchant.id

        response = self.client.post(f'/growlee-control/merchants/{merchant.id}/', {'action': 'delete_merchant', 'confirm_name': merchant.name})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action='staff.merchant.delete', target_type='Merchant', target_id=str(merchant_id)).exists())


@override_settings(STORAGES=TEST_STORAGES)
class AuditLogActionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('merchant-owner', password='secret-12345')
        self.merchant = Merchant.objects.create(
            name='Audit Shop',
            slug='audit-shop',
            is_active=True,
            onboarding_completed=True,
            onboarding_fee_paid=True,
            flyer_style='premium',
            flyer_visual_approved=True,
        )
        Subscription.objects.create(merchant=self.merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        MerchantMembership.objects.create(user=self.owner, merchant=self.merchant, role='owner')
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='Audit Campaign', is_active=True)
        self.customer = Customer.objects.create(merchant=self.merchant, phone='+33644444444', email='audit@example.test')
        self.session = GameSession.objects.create(customer=self.customer, campaign=self.campaign, reward_label='Dessert offert', is_winner=True)
        self.client.force_login(self.owner)

    def test_delete_customer_creates_audit_log(self):
        response = self.client.post(f'/admin/customers/{self.customer.id}/delete/')

        self.assertEqual(response.status_code, 302)
        log = AuditLog.objects.get(action='merchant.customer.delete')
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.merchant, self.merchant)
        self.assertEqual(log.target_type, 'Customer')
        self.assertEqual(log.target_id, str(self.customer.id))
        self.assertEqual(log.metadata['phone'], '+33644444444')

    def test_redeem_session_creates_audit_log(self):
        response = self.client.post(f'/admin/sessions/{self.session.id}/redeem/')

        self.assertEqual(response.status_code, 302)
        log = AuditLog.objects.get(action='merchant.session.redeem')
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.merchant, self.merchant)
        self.assertEqual(log.target_type, 'GameSession')
        self.assertEqual(log.target_id, str(self.session.id))
        self.assertEqual(log.metadata['reward_label'], 'Dessert offert')

    def test_toggle_campaign_module_creates_audit_log(self):
        response = self.client.post('/admin/campaign/toggle/', {
            'campaign_id': self.campaign.id,
            'flag': 'wallet_enabled',
            'value': '0',
        })

        self.assertEqual(response.status_code, 302)
        log = AuditLog.objects.get(action='merchant.campaign.module_toggle')
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.merchant, self.merchant)
        self.assertEqual(log.target_type, 'Campaign')
        self.assertEqual(log.target_id, str(self.campaign.id))
        self.assertEqual(log.metadata['flag'], 'wallet_enabled')
        self.assertFalse(log.metadata['enabled'])
