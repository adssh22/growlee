import csv
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.campaigns.models import Campaign, EntryPoint
from apps.core.billing import handle_checkout_session_completed, handle_invoice_payment_failed, handle_invoice_payment_succeeded, handle_stripe_subscription_event, map_stripe_subscription_status
from apps.core.common_views import _merchant_context_for_user, _merchant_is_unlocked
from apps.customers.models import Customer, GameSession, WalletPass
from apps.core.models import AuditLog, MerchantDailyMetric
from apps.core.totp import generate_secret
from apps.merchants.models import Merchant, Subscription
from apps.accounts.models import MerchantMembership, StaffMFA
from apps.rewards.models import Reward


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class MerchantDailyMetricTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('metrics-owner', password='secret-12345')
        self.merchant = Merchant.objects.create(name='Metrics Shop', slug='metrics-shop', is_active=True, onboarding_fee_paid=True)
        self.other_merchant = Merchant.objects.create(name='Other Metrics Shop', slug='other-metrics-shop', is_active=True)
        MerchantMembership.objects.create(user=self.user, merchant=self.merchant, role='owner')
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='Metrics Campaign', is_active=True)
        self.other_campaign = Campaign.objects.create(merchant=self.other_merchant, name='Other Metrics Campaign', is_active=True)

    def test_rebuild_daily_metrics_creates_aggregates(self):
        customer = Customer.objects.create(merchant=self.merchant, phone='+33670000001')
        winner = GameSession.objects.create(customer=customer, campaign=self.campaign, reward_label='Café', is_winner=True, redeemed=True)
        GameSession.objects.create(customer=customer, campaign=self.campaign, reward_label='Perdu', is_winner=False, redeemed=False)
        WalletPass.objects.create(customer=customer, campaign=self.campaign, provider='apple', serial_number='metric-pass-1')

        call_command('rebuild_daily_metrics')

        metric = MerchantDailyMetric.objects.get(merchant=self.merchant, date=winner.created_at.date())
        self.assertEqual(metric.scans_count, 2)
        self.assertEqual(metric.contacts_count, 1)
        self.assertEqual(metric.winners_count, 1)
        self.assertEqual(metric.redeemed_count, 1)
        self.assertEqual(metric.wallet_passes_count, 1)

    def test_rebuild_daily_metrics_can_filter_merchant_and_since(self):
        customer = Customer.objects.create(merchant=self.merchant, phone='+33670000002')
        other_customer = Customer.objects.create(merchant=self.other_merchant, phone='+33670000003')
        old_session = GameSession.objects.create(customer=customer, campaign=self.campaign, reward_label='Old', is_winner=True)
        GameSession.objects.create(customer=other_customer, campaign=self.other_campaign, reward_label='Other', is_winner=True)
        old_date = timezone.now() - timezone.timedelta(days=3)
        Customer.objects.filter(id=customer.id).update(created_at=old_date)
        GameSession.objects.filter(id=old_session.id).update(created_at=old_date)

        call_command('rebuild_daily_metrics', merchant_id=self.merchant.id, since=timezone.now().date().isoformat())

        self.assertFalse(MerchantDailyMetric.objects.filter(merchant=self.other_merchant).exists())
        self.assertFalse(MerchantDailyMetric.objects.filter(merchant=self.merchant).exists())

    def test_merchant_context_uses_metrics_when_available(self):
        Customer.objects.create(merchant=self.merchant, phone='+33670000004')
        MerchantDailyMetric.objects.create(
            merchant=self.merchant,
            date=timezone.localdate(),
            scans_count=10,
            contacts_count=4,
            winners_count=7,
            redeemed_count=3,
            wallet_passes_count=2,
        )

        context = _merchant_context_for_user(self.user)

        self.assertEqual(context['stats']['scans'], 10)
        self.assertEqual(context['stats']['contacts'], 4)
        self.assertEqual(context['stats']['gains_won'], 7)
        self.assertEqual(context['stats']['redeemed'], 3)
        self.assertEqual(context['stats']['gains_waiting'], 4)
        self.assertEqual(context['stats']['wallets'], 2)
        self.assertEqual(context['stats']['return_rate'], '30%')

    def test_merchant_context_falls_back_to_live_counts_without_metrics(self):
        customer = Customer.objects.create(merchant=self.merchant, phone='+33670000005')
        GameSession.objects.create(customer=customer, campaign=self.campaign, reward_label='Live', is_winner=True, redeemed=True)

        context = _merchant_context_for_user(self.user)

        self.assertEqual(context['stats']['scans'], 1)
        self.assertEqual(context['stats']['contacts'], 1)
        self.assertEqual(context['stats']['gains_won'], 1)
        self.assertEqual(context['stats']['redeemed'], 1)


class StripeBillingTests(TestCase):
    def test_maps_stripe_subscription_statuses(self):
        self.assertEqual(map_stripe_subscription_status('active'), Subscription.STATUS_ACTIVE)
        self.assertEqual(map_stripe_subscription_status('trialing'), Subscription.STATUS_TRIALING)
        self.assertEqual(map_stripe_subscription_status('past_due'), Subscription.STATUS_PAST_DUE)
        self.assertEqual(map_stripe_subscription_status('canceled'), Subscription.STATUS_CANCELED)
        self.assertEqual(map_stripe_subscription_status('unpaid'), Subscription.STATUS_SUSPENDED)
        self.assertEqual(map_stripe_subscription_status('unknown-new-status'), Subscription.STATUS_SUSPENDED)

    def test_checkout_session_completed_activates_merchant_and_subscription(self):
        merchant = Merchant.objects.create(name='Stripe Shop', slug='stripe-shop', is_active=False)

        subscription = handle_checkout_session_completed({
            'id': 'cs_test_123',
            'customer': 'cus_123',
            'subscription': 'sub_123',
            'metadata': {'merchant_id': str(merchant.id)},
        })

        merchant.refresh_from_db()
        self.assertTrue(merchant.is_active)
        self.assertTrue(merchant.onboarding_fee_paid)
        self.assertEqual(subscription.provider, Subscription.PROVIDER_STRIPE)
        self.assertEqual(subscription.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(subscription.provider_customer_id, 'cus_123')
        self.assertEqual(subscription.provider_subscription_id, 'sub_123')
        self.assertTrue(AuditLog.objects.filter(action='billing.stripe.checkout_completed', merchant=merchant).exists())

    def test_invoice_payment_failed_marks_subscription_past_due(self):
        merchant = Merchant.objects.create(name='Late Stripe Shop', slug='late-stripe-shop', is_active=True, onboarding_fee_paid=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_STRIPE, provider_customer_id='cus_late', provider_subscription_id='sub_late')

        subscription = handle_invoice_payment_failed({'id': 'in_failed', 'customer': 'cus_late', 'subscription': 'sub_late'})

        self.assertEqual(subscription.status, Subscription.STATUS_PAST_DUE)
        self.assertEqual(subscription.provider, Subscription.PROVIDER_STRIPE)

    def test_invoice_payment_succeeded_marks_subscription_active(self):
        merchant = Merchant.objects.create(name='Recovered Stripe Shop', slug='recovered-stripe-shop', is_active=False, onboarding_fee_paid=False)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_PAST_DUE, provider=Subscription.PROVIDER_STRIPE, provider_customer_id='cus_recovered', provider_subscription_id='sub_recovered')

        subscription = handle_invoice_payment_succeeded({'id': 'in_paid', 'customer': 'cus_recovered', 'subscription': 'sub_recovered'})

        merchant.refresh_from_db()
        self.assertTrue(merchant.is_active)
        self.assertTrue(merchant.onboarding_fee_paid)
        self.assertEqual(subscription.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(subscription.provider, Subscription.PROVIDER_STRIPE)

    def test_deleted_stripe_subscription_marks_subscription_canceled(self):
        merchant = Merchant.objects.create(name='Canceled Stripe Shop', slug='canceled-stripe-shop', is_active=True, onboarding_fee_paid=True)
        Subscription.objects.create(merchant=merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_STRIPE, provider_customer_id='cus_cancel', provider_subscription_id='sub_cancel')

        subscription = handle_stripe_subscription_event({
            'id': 'sub_cancel',
            'customer': 'cus_cancel',
            'status': 'canceled',
        })

        self.assertEqual(subscription.status, Subscription.STATUS_CANCELED)
        self.assertEqual(subscription.provider, Subscription.PROVIDER_STRIPE)

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    def test_stripe_webhook_without_matching_merchant_does_not_500(self):
        event = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_missing_merchant',
                    'customer': 'cus_missing',
                    'subscription': 'sub_missing',
                    'metadata': {'merchant_id': '999999'},
                }
            },
        }

        with mock.patch('apps.core.stripe_views.stripe.Webhook.construct_event', return_value=event):
            response = self.client.post('/webhooks/stripe/', data=b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='valid')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Subscription.objects.filter(provider_subscription_id='sub_missing').exists())

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    def test_stripe_webhook_routes_checkout_completed_event(self):
        merchant = Merchant.objects.create(name='Webhook Shop', slug='webhook-shop', is_active=False)
        event = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_webhook',
                    'customer': 'cus_webhook',
                    'subscription': 'sub_webhook',
                    'metadata': {'merchant_id': str(merchant.id)},
                }
            },
        }

        with mock.patch('apps.core.stripe_views.stripe.Webhook.construct_event', return_value=event):
            response = self.client.post('/webhooks/stripe/', data=b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='valid')

        self.assertEqual(response.status_code, 200)
        merchant.refresh_from_db()
        self.assertTrue(merchant.onboarding_fee_paid)
        self.assertEqual(merchant.subscription.status, Subscription.STATUS_ACTIVE)

    @override_settings(
        STRIPE_SECRET_KEY='sk_test_123',
        STRIPE_PRICE_ID_PRO='price_123',
        STRIPE_SUCCESS_URL='https://example.test/success',
        STRIPE_CANCEL_URL='https://example.test/cancel',
    )
    def test_merchant_checkout_creates_stripe_session_when_configured(self):
        user = User.objects.create_user('stripe-owner', email='owner@example.test', password='secret-12345')
        merchant = Merchant.objects.create(name='Checkout Shop', slug='checkout-shop', contact_email='billing@example.test', is_active=False)
        MerchantMembership.objects.create(user=user, merchant=merchant, role='owner')
        self.client.force_login(user)
        stripe_session = mock.Mock(id='cs_test_created', url='https://checkout.stripe.test/session')

        with mock.patch('apps.core.merchant_views.stripe.checkout.Session.create', return_value=stripe_session) as create_session:
            response = self.client.get('/admin/checkout/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://checkout.stripe.test/session')
        create_session.assert_called_once()
        kwargs = create_session.call_args.kwargs
        self.assertEqual(kwargs['line_items'], [{'price': 'price_123', 'quantity': 1}])
        self.assertEqual(kwargs['metadata'], {'merchant_id': str(merchant.id)})
        self.assertEqual(kwargs['subscription_data'], {'metadata': {'merchant_id': str(merchant.id)}})
        self.assertTrue(AuditLog.objects.filter(action='billing.stripe.checkout_created', merchant=merchant).exists())


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
class MerchantOnboardingChecklistTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('launch-owner', 'launch-owner@example.test', 'secret-12345')
        self.manager = User.objects.create_user('launch-manager', 'launch-manager@example.test', 'secret-12345')
        self.staff = User.objects.create_user('launch-staff', 'launch-staff@example.test', 'secret-12345')
        self.merchant = Merchant.objects.create(
            name='Launch Shop',
            slug='launch-shop',
            address='1 rue du Test',
            business_sector='Restaurant',
            contact_email='owner@launch.test',
            google_review_url='https://example.test/review',
            is_active=True,
            onboarding_completed=True,
            onboarding_fee_paid=True,
            public_journey_tested=True,
        )
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='Launch Campaign', is_active=True)
        Reward.objects.create(merchant=self.merchant, campaign=self.campaign, name='Café', description='Café offert', active=True)
        EntryPoint.objects.create(merchant=self.merchant, campaign=self.campaign, name='QR principal', code='launch-shop-qr-main', channel='qr')
        Subscription.objects.create(merchant=self.merchant, status=Subscription.STATUS_ACTIVE, provider=Subscription.PROVIDER_MANUAL)
        MerchantMembership.objects.create(user=self.owner, merchant=self.merchant, role='owner')
        MerchantMembership.objects.create(user=self.manager, merchant=self.merchant, role='manager')
        MerchantMembership.objects.create(user=self.staff, merchant=self.merchant, role='staff')

    def test_onboarding_checklist_shows_complete_launch_progress(self):
        self.client.force_login(self.owner)

        response = self.client.get('/admin/onboarding/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Votre commerce est prêt à être lancé')
        self.assertContains(response, '100%')
        self.assertContains(response, '/admin/qr/launch-shop-qr-main.svg')
        self.assertEqual(response.context['onboarding_progress'], 100)

    def test_manager_can_view_onboarding_but_staff_cannot(self):
        self.client.force_login(self.manager)
        response = self.client.get('/admin/onboarding/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Plan de lancement boutique')

        account_response = self.client.get('/admin/account/')
        self.assertEqual(account_response.status_code, 302)
        self.assertEqual(account_response['Location'], '/admin/onboarding/')

        self.client.force_login(self.staff)
        response = self.client.get('/admin/onboarding/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/admin/employee/')

    def test_onboarding_mark_public_journey_tested_flag(self):
        self.merchant.public_journey_tested = False
        self.merchant.save(update_fields=['public_journey_tested'])
        self.client.force_login(self.owner)

        response = self.client.post('/admin/onboarding/', {'form_action': 'mark_public_journey_tested'})

        self.assertEqual(response.status_code, 302)
        self.merchant.refresh_from_db()
        self.assertTrue(self.merchant.public_journey_tested)
        self.assertTrue(AuditLog.objects.filter(action='merchant.onboarding.public_journey_tested', merchant=self.merchant).exists())

    def test_onboarding_progress_is_partial_when_data_missing(self):
        self.merchant.google_review_url = ''
        self.merchant.public_journey_tested = False
        self.merchant.onboarding_fee_paid = False
        self.merchant.save(update_fields=['google_review_url', 'public_journey_tested', 'onboarding_fee_paid'])
        Subscription.objects.filter(merchant=self.merchant).update(status=Subscription.STATUS_SUSPENDED)
        self.client.force_login(self.owner)

        response = self.client.get('/admin/onboarding/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Prochaine étape')
        self.assertLess(response.context['onboarding_progress'], 100)
        self.assertFalse(response.context['onboarding_ready'])


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

    def test_customers_list_is_paginated_and_shows_latest_session(self):
        for index in range(30):
            customer = Customer.objects.create(merchant=self.merchant, phone=f'+33655555{index:03d}', email=f'client{index}@example.test')
            GameSession.objects.create(customer=customer, campaign=self.campaign, reward_label=f'Gain {index}', is_winner=True)

        response = self.client.get('/admin/customers/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['customers']), 25)
        self.assertTrue(response.context['page_obj'].has_next())
        self.assertContains(response, 'Gain 29')
        self.assertContains(response, 'Suivant')

    def test_customers_export_csv_uses_annotated_session_count(self):
        response = self.client.get('/admin/customers/export/')

        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(response.content.decode().splitlines()))
        row = next(row for row in rows if row['phone'] == self.customer.phone)
        self.assertEqual(row['sessions_count'], '1')

    def test_reward_delete_archives_and_hides_reward_without_deleting_history(self):
        reward = Reward.objects.create(merchant=self.merchant, campaign=self.campaign, name='Archive reward', description='Archive reward', active=True)
        session = GameSession.objects.create(customer=self.customer, campaign=self.campaign, reward=reward, reward_label='Archive reward', is_winner=True)

        response = self.client.post(f'/admin/rewards/{reward.id}/delete/')

        self.assertEqual(response.status_code, 302)
        reward.refresh_from_db()
        self.assertTrue(Reward.objects.filter(id=reward.id).exists())
        self.assertTrue(reward.is_archived)
        self.assertFalse(reward.active)
        self.assertEqual(reward.archived_by, self.owner)
        self.assertTrue(GameSession.objects.filter(id=session.id, reward=reward, reward_label='Archive reward').exists())
        self.assertTrue(AuditLog.objects.filter(action='merchant.reward.archive', merchant=self.merchant, target_type='Reward', target_id=str(reward.id)).exists())

        response = self.client.get('/admin/game/')
        self.assertNotContains(response, 'Archive reward')

    def test_reward_restore_action_restores_archived_reward(self):
        reward = Reward.objects.create(merchant=self.merchant, campaign=self.campaign, name='Restore reward', description='Restore reward', active=False, archived_at=timezone.now(), archived_by=self.owner)

        response = self.client.post(f'/admin/rewards/{reward.id}/delete/', {'action': 'restore'})

        self.assertEqual(response.status_code, 302)
        reward.refresh_from_db()
        self.assertFalse(reward.is_archived)
        self.assertIsNone(reward.archived_by)
        self.assertTrue(AuditLog.objects.filter(action='merchant.reward.restore', merchant=self.merchant, target_type='Reward', target_id=str(reward.id)).exists())

    def test_delete_customer_soft_deletes_hides_from_crm_and_creates_audit_log(self):
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

        list_response = self.client.get('/admin/customers/')
        export_response = self.client.get('/admin/customers/export/')
        self.assertNotContains(list_response, '+33644444444')
        rows = list(csv.DictReader(export_response.content.decode().splitlines()))
        self.assertNotIn('+33644444444', {row['phone'] for row in rows})

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
