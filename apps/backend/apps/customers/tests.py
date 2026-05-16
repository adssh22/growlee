from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.campaigns.models import Campaign, WheelSegment
from apps.customers.models import Customer, GameSession
from apps.customers.services import claim_reward
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


class CustomerConsentTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(name='Consent Shop', slug='consent-shop', is_active=True)
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='Consent campaign', game_type='quiz', is_active=True)

    def test_marketing_consent_is_false_by_default_and_reward_is_created(self):
        customer, session, _ = claim_reward(
            merchant=self.merchant,
            campaign=self.campaign,
            phone='+33600000001',
            email='client@example.test',
        )

        self.assertFalse(customer.consent_marketing)
        self.assertIsNone(customer.consent_marketing_at)
        self.assertEqual(session.customer, customer)

    def test_marketing_consent_is_stored_only_when_checked(self):
        customer, session, _ = claim_reward(
            merchant=self.merchant,
            campaign=self.campaign,
            phone='+33600000002',
            email='optin@example.test',
            consent_marketing=True,
        )

        self.assertTrue(customer.consent_marketing)
        self.assertIsNotNone(customer.consent_marketing_at)
        self.assertEqual(session.customer, customer)

    def test_existing_marketing_consent_is_not_removed_by_later_claim_without_checkbox(self):
        customer, _, _ = claim_reward(
            merchant=self.merchant,
            campaign=self.campaign,
            phone='+33600000003',
            consent_marketing=True,
        )
        consented_at = customer.consent_marketing_at

        customer, session, _ = claim_reward(
            merchant=self.merchant,
            campaign=self.campaign,
            phone='+33600000003',
            consent_marketing=False,
        )

        self.assertTrue(customer.consent_marketing)
        self.assertEqual(customer.consent_marketing_at, consented_at)
        self.assertEqual(session.customer, customer)


class RewardQuotaTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(name='Quota Shop', slug='quota-shop', is_active=True)
        self.campaign = Campaign.objects.create(merchant=self.merchant, name='Quota campaign', game_type='quiz', is_active=True)

    def _customer(self, phone='+33000000000'):
        return Customer.objects.create(merchant=self.merchant, phone=phone)

    def test_reward_under_daily_quota_can_be_distributed(self):
        reward = Reward.objects.create(
            merchant=self.merchant,
            campaign=self.campaign,
            name='Dessert offert',
            description='Dessert offert',
            probability_weight=100,
            daily_quota=1,
            active=True,
        )

        _, session, _ = claim_reward(merchant=self.merchant, campaign=self.campaign, phone='+33111111111')

        self.assertTrue(session.is_winner)
        self.assertEqual(session.reward, reward)
        reward.refresh_from_db()
        self.assertEqual(reward.total_distributed, 1)

    def test_reward_at_daily_quota_is_not_distributed(self):
        exhausted = Reward.objects.create(
            merchant=self.merchant,
            campaign=self.campaign,
            name='Café offert',
            description='Café offert',
            probability_weight=100,
            daily_quota=1,
            active=True,
        )
        available = Reward.objects.create(
            merchant=self.merchant,
            campaign=self.campaign,
            name='Dessert offert',
            description='Dessert offert',
            probability_weight=100,
            daily_quota=5,
            active=True,
        )
        GameSession.objects.create(
            customer=self._customer(),
            campaign=self.campaign,
            reward=exhausted,
            reward_label=exhausted.description,
            claim_token='already-won',
            is_winner=True,
        )

        _, session, _ = claim_reward(merchant=self.merchant, campaign=self.campaign, phone='+33222222222')

        self.assertTrue(session.is_winner)
        self.assertEqual(session.reward, available)

    def test_yesterday_distribution_does_not_count_for_daily_quota(self):
        reward = Reward.objects.create(
            merchant=self.merchant,
            campaign=self.campaign,
            name='Boisson offerte',
            description='Boisson offerte',
            probability_weight=100,
            daily_quota=1,
            active=True,
        )
        previous = GameSession.objects.create(
            customer=self._customer(),
            campaign=self.campaign,
            reward=reward,
            reward_label=reward.description,
            claim_token='yesterday-win',
            is_winner=True,
        )
        GameSession.objects.filter(pk=previous.pk).update(created_at=timezone.now() - timedelta(days=1))

        _, session, _ = claim_reward(merchant=self.merchant, campaign=self.campaign, phone='+33333333333')

        self.assertTrue(session.is_winner)
        self.assertEqual(session.reward, reward)

    def test_segment_at_daily_quota_is_excluded_from_weighted_choice(self):
        self.campaign.game_type = 'spin'
        self.campaign.save(update_fields=['game_type'])
        exhausted_reward = Reward.objects.create(
            merchant=self.merchant,
            campaign=self.campaign,
            name='Upgrade',
            description='Upgrade',
            probability_weight=100,
            daily_quota=5,
            active=True,
        )
        available_reward = Reward.objects.create(
            merchant=self.merchant,
            campaign=self.campaign,
            name='Dessert',
            description='Dessert',
            probability_weight=100,
            daily_quota=5,
            active=True,
        )
        exhausted_segment = WheelSegment.objects.create(
            campaign=self.campaign,
            reward=exhausted_reward,
            label='Upgrade terrain',
            probability_weight=100,
            daily_quota=1,
            active=True,
            display_order=1,
        )
        available_segment = WheelSegment.objects.create(
            campaign=self.campaign,
            reward=available_reward,
            label='Dessert offert',
            probability_weight=100,
            daily_quota=5,
            active=True,
            display_order=2,
        )
        GameSession.objects.create(
            customer=self._customer(),
            campaign=self.campaign,
            reward=exhausted_reward,
            reward_label=exhausted_segment.label,
            claim_token='segment-won',
            is_winner=True,
        )

        _, session, segment = claim_reward(merchant=self.merchant, campaign=self.campaign, phone='+33444444444')

        self.assertTrue(session.is_winner)
        self.assertEqual(segment, available_segment)
        self.assertEqual(session.reward, available_reward)
        self.assertEqual(session.reward_label, available_segment.label)

    def test_no_available_reward_creates_non_winning_session_without_error(self):
        reward = Reward.objects.create(
            merchant=self.merchant,
            campaign=self.campaign,
            name='Cadeau du jour',
            description='Cadeau du jour',
            probability_weight=100,
            daily_quota=1,
            active=True,
        )
        GameSession.objects.create(
            customer=self._customer(),
            campaign=self.campaign,
            reward=reward,
            reward_label=reward.description,
            claim_token='quota-used',
            is_winner=True,
        )

        _, session, segment = claim_reward(merchant=self.merchant, campaign=self.campaign, phone='+33555555555')

        self.assertIsNone(segment)
        self.assertIsNone(session.reward)
        self.assertFalse(session.is_winner)
        self.assertEqual(session.reward_label, 'Aucun gain disponible aujourd’hui')
