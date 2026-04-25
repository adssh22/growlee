from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.accounts.models import MerchantMembership
from apps.campaigns.models import Campaign, EntryPoint
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


class Command(BaseCommand):
    help = 'Seed demo data for Growlee'

    def handle(self, *args, **options):
        merchant, _ = Merchant.objects.get_or_create(
            slug='demo-bistro',
            defaults={
                'name': 'Demo Bistro',
                'primary_color': '#111827',
                'accent_color': '#f59e0b',
                'is_active': True,
            },
        )

        campaign, _ = Campaign.objects.get_or_create(
            merchant=merchant,
            name='Campagne Printemps',
            defaults={
                'game_type': 'spin',
                'reward_label': 'Dessert offert à la prochaine visite',
                'is_active': True,
            },
        )

        EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=campaign,
            code='demo-counter-001',
            defaults={
                'name': 'QR Comptoir',
                'channel': 'qr',
                'placement': 'counter',
            },
        )

        Reward.objects.get_or_create(
            merchant=merchant,
            campaign=campaign,
            name='Dessert offert',
            defaults={
                'reward_type': 'gift',
                'description': 'Dessert offert à la prochaine visite',
                'probability_weight': 100,
                'daily_quota': 50,
                'active': True,
                'expires_in_hours': 168,
            },
        )

        user, created = User.objects.get_or_create(
            username='demo',
            defaults={
                'email': 'demo@growlee.local',
                'is_staff': True,
            },
        )
        if created:
            user.set_password('demo1234')
            user.save()

        MerchantMembership.objects.get_or_create(
            user=user,
            merchant=merchant,
            defaults={'role': 'owner'},
        )

        self.stdout.write(self.style.SUCCESS('Demo seed ready. login=demo password=demo1234'))
