import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import MerchantMembership
from apps.campaigns.models import Campaign, EntryPoint
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


class Command(BaseCommand):
    help = 'Seed demo data for Growlee'

    def handle(self, *args, **options):
        allow_prod_seed = os.getenv('ALLOW_DEMO_SEED', '').strip().lower() in {'1', 'true', 'yes', 'on'}
        if not settings.DEBUG and not allow_prod_seed:
            raise CommandError(
                'Refusing to seed demo accounts while DJANGO_DEBUG=0. '
                'Set ALLOW_DEMO_SEED=1 only if you intentionally want demo credentials in this environment.'
            )

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

        merchant_user, created = User.objects.get_or_create(
            username='demo-merchant',
            defaults={
                'email': 'merchant@growlee.local',
                'is_staff': False,
                'is_superuser': False,
            },
        )
        if created:
            merchant_user.set_password('demo1234')
            merchant_user.save()

        MerchantMembership.objects.get_or_create(
            user=merchant_user,
            merchant=merchant,
            defaults={'role': 'owner'},
        )

        admin_user, created = User.objects.get_or_create(
            username='demo',
            defaults={
                'email': 'demo@growlee.local',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if created:
            admin_user.set_password('demo1234')
            admin_user.save()
        elif not admin_user.is_superuser:
            admin_user.is_staff = True
            admin_user.is_superuser = True
            admin_user.save(update_fields=['is_staff', 'is_superuser'])

        # Séparation stricte : le superuser n'est pas owner d'un commerce.
        MerchantMembership.objects.filter(user=admin_user).delete()

        self.stdout.write(self.style.SUCCESS('Demo seed ready. superuser=demo/demo1234 merchant=demo-merchant/demo1234'))
