from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.campaigns.models import Campaign, EntryPoint
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

    def test_staff_archive_and_restore_merchant_soft_deletes_without_removing_users(self):
        merchant = Merchant.objects.create(name='Archive Audit Shop', slug='archive-audit-shop', is_active=True)
        owner = User.objects.create_user('archive-owner', password='secret-12345')
        MerchantMembership.objects.create(user=owner, merchant=merchant, role='owner')
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        merchant_id = merchant.id

        response = self.client.post(f'/growlee-control/merchants/{merchant.id}/', {'action': 'archive_merchant', 'confirm_name': merchant.name})

        self.assertEqual(response.status_code, 302)
        merchant.refresh_from_db()
        self.assertFalse(merchant.is_active)
        self.assertIsNotNone(merchant.deleted_at)
        self.assertTrue(User.objects.filter(id=owner.id).exists())
        self.assertTrue(Merchant.objects.filter(id=merchant_id).exists())
        self.assertTrue(AuditLog.objects.filter(action='staff.merchant.archive', target_type='Merchant', target_id=str(merchant_id)).exists())
        self.assertEqual(merchant.subscription.status, Subscription.STATUS_SUSPENDED)

        response = self.client.post(f'/growlee-control/merchants/{merchant.id}/', {'action': 'restore_merchant'})

        self.assertEqual(response.status_code, 302)
        merchant.refresh_from_db()
        self.assertTrue(merchant.is_active)
        self.assertIsNone(merchant.deleted_at)
        self.assertTrue(AuditLog.objects.filter(action='staff.merchant.restore', target_type='Merchant', target_id=str(merchant_id)).exists())

    def test_archived_merchants_are_hidden_by_default_and_visible_with_filter(self):
        active = Merchant.objects.create(name='Visible Shop', slug='visible-shop', is_active=True)
        archived = Merchant.objects.create(name='Archived Shop', slug='archived-shop', is_active=False, deleted_at=timezone.now(), deleted_by=self.user)
        Subscription.objects.create(merchant=active, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        Subscription.objects.create(merchant=archived, status=Subscription.STATUS_SUSPENDED, provider=Subscription.PROVIDER_MANUAL)

        default_response = self.client.get('/growlee-control/merchants/')
        archived_response = self.client.get('/growlee-control/merchants/?archived=yes')

        self.assertContains(default_response, 'Visible Shop')
        self.assertNotContains(default_response, 'Archived Shop')
        self.assertContains(archived_response, 'Archived Shop')
        self.assertNotContains(archived_response, 'Visible Shop')

    def test_archived_merchant_does_not_serve_public_play_page(self):
        merchant = Merchant.objects.create(name='Archived Public Shop', slug='archived-public-shop', is_active=False, deleted_at=timezone.now(), deleted_by=self.user)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_SUSPENDED, provider=Subscription.PROVIDER_MANUAL)

        response = self.client.get('/play/archived-public-shop/')

        self.assertEqual(response.status_code, 404)

    def test_support_search_finds_grouped_results_and_logs_audit(self):
        merchant = Merchant.objects.create(name='Support Bakery', slug='support-bakery', is_active=True, contact_email='owner@support.test')
        campaign = Campaign.objects.create(merchant=merchant, name='Support Campaign', is_active=True)
        customer = Customer.objects.create(merchant=merchant, phone='+33677777777', email='client@support.test', first_name='Sofia')
        session = GameSession.objects.create(customer=customer, campaign=campaign, reward_label='Café offert', claim_code='SUPPORT42', claim_token='support-token-42')
        entry = EntryPoint.objects.create(merchant=merchant, campaign=campaign, name='QR support', code='support-qr-main')

        merchant_response = self.client.get('/growlee-control/support/?q=support-bakery')
        customer_response = self.client.get('/growlee-control/support/?q=+33677777777')
        session_response = self.client.get('/growlee-control/support/?q=SUPPORT42')
        entry_response = self.client.get('/growlee-control/support/?q=support-qr')

        self.assertContains(merchant_response, 'Support Bakery')
        self.assertContains(customer_response, '+33677777777')
        self.assertContains(session_response, 'SUPPORT42')
        self.assertContains(entry_response, 'support-qr-main')
        self.assertContains(session_response, f'/gain/{session.claim_token}/')
        self.assertContains(entry_response, f'/admin/qr/{entry.code}.svg')
        self.assertTrue(AuditLog.objects.filter(action='staff.support.search', actor=self.user).exists())

    def test_support_search_requires_superuser_and_mfa(self):
        owner = User.objects.create_user('merchant-support-owner', password='secret-12345')
        self.client.force_login(owner)
        response = self.client.get('/growlee-control/support/?q=anything')
        self.assertNotEqual(response.status_code, 200)

        staff_without_mfa = User.objects.create_superuser('staff-no-mfa', 'no-mfa@example.test', 'secret-12345')
        self.client.force_login(staff_without_mfa)
        response = self.client.get('/growlee-control/support/?q=anything')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/growlee-control/mfa/setup/')


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

    def test_delete_customer_soft_deletes_and_creates_audit_log(self):
        response = self.client.post(f'/admin/customers/{self.customer.id}/delete/')

        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.deleted_at)
        self.assertEqual(self.customer.deleted_by, self.owner)
        self.assertTrue(GameSession.objects.filter(id=self.session.id, customer=self.customer).exists())
        log = AuditLog.objects.get(action='merchant.customer.archive')
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
