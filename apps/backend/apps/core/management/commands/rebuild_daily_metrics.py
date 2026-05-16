from collections import defaultdict
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.customers.models import Customer, GameSession, WalletPass
from apps.core.models import MerchantDailyMetric
from apps.merchants.models import Merchant


class Command(BaseCommand):
    help = 'Rebuild aggregated daily merchant analytics metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--merchant-id', type=int, help='Only rebuild metrics for one merchant id.')
        parser.add_argument('--since', type=str, help='Only rebuild metrics from this date included (YYYY-MM-DD).')

    def handle(self, *args, **options):
        merchant_id = options.get('merchant_id')
        since = self._parse_since(options.get('since'))

        merchants = Merchant.objects.all()
        if merchant_id:
            merchants = merchants.filter(id=merchant_id)
            if not merchants.exists():
                raise CommandError(f'Merchant not found: {merchant_id}')

        deleted = MerchantDailyMetric.objects.filter(merchant__in=merchants)
        if since:
            deleted = deleted.filter(date__gte=since)
        deleted_count, _ = deleted.delete()

        rows = self._build_rows(merchants, since)
        with transaction.atomic():
            MerchantDailyMetric.objects.bulk_create(rows, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Rebuilt daily metrics: merchants={merchants.count()}, deleted={deleted_count}, created={len(rows)}'
        ))

    def _parse_since(self, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError('--since must use YYYY-MM-DD') from exc

    def _build_rows(self, merchants, since):
        merchant_ids = list(merchants.values_list('id', flat=True))
        if not merchant_ids:
            return []

        buckets = defaultdict(lambda: {
            'scans_count': 0,
            'contacts_count': 0,
            'winners_count': 0,
            'redeemed_count': 0,
            'review_clicks_count': 0,
            'wallet_passes_count': 0,
        })

        sessions = GameSession.objects.filter(campaign__merchant_id__in=merchant_ids)
        customers = Customer.objects.filter(merchant_id__in=merchant_ids, deleted_at__isnull=True)
        wallet_passes = WalletPass.objects.filter(campaign__merchant_id__in=merchant_ids)
        if since:
            sessions = sessions.filter(created_at__date__gte=since)
            customers = customers.filter(created_at__date__gte=since)
            wallet_passes = wallet_passes.filter(created_at__date__gte=since)

        for row in sessions.annotate(day=TruncDate('created_at')).values('campaign__merchant_id', 'day').annotate(
            scans_count=Count('id'),
            winners_count=Count('id', filter=Q(is_winner=True)),
            redeemed_count=Count('id', filter=Q(redeemed=True)),
        ):
            bucket = buckets[(row['campaign__merchant_id'], row['day'])]
            bucket['scans_count'] = row['scans_count']
            bucket['winners_count'] = row['winners_count']
            bucket['redeemed_count'] = row['redeemed_count']

        for row in customers.annotate(day=TruncDate('created_at')).values('merchant_id', 'day').annotate(contacts_count=Count('id')):
            buckets[(row['merchant_id'], row['day'])]['contacts_count'] = row['contacts_count']

        for row in wallet_passes.annotate(day=TruncDate('created_at')).values('campaign__merchant_id', 'day').annotate(wallet_passes_count=Count('id')):
            buckets[(row['campaign__merchant_id'], row['day'])]['wallet_passes_count'] = row['wallet_passes_count']

        now = timezone.now()
        return [
            MerchantDailyMetric(
                merchant_id=merchant_id,
                date=day,
                scans_count=counts['scans_count'],
                contacts_count=counts['contacts_count'],
                winners_count=counts['winners_count'],
                redeemed_count=counts['redeemed_count'],
                review_clicks_count=counts['review_clicks_count'],
                wallet_passes_count=counts['wallet_passes_count'],
                created_at=now,
                updated_at=now,
            )
            for (merchant_id, day), counts in sorted(buckets.items())
        ]
