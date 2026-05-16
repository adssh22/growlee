from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.customers.models import NotificationJob
from apps.customers.services import process_notification_job


class Command(BaseCommand):
    help = 'Process pending Growlee notification jobs. Use --include-failed to retry failed jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Maximum jobs to process.')
        parser.add_argument('--include-failed', action='store_true', help='Retry failed jobs too.')
        parser.add_argument('--channel', choices=[NotificationJob.CHANNEL_EMAIL, NotificationJob.CHANNEL_SMS], help='Only process one channel.')

    def handle(self, *args, **options):
        statuses = [NotificationJob.STATUS_PENDING]
        if options['include_failed']:
            statuses.append(NotificationJob.STATUS_FAILED)
        jobs = NotificationJob.objects.filter(status__in=statuses, scheduled_at__lte=timezone.now()).order_by('scheduled_at', 'id')
        if options.get('channel'):
            jobs = jobs.filter(channel=options['channel'])
        jobs = list(jobs[:max(1, options['limit'])])
        sent = failed = 0
        for job in jobs:
            processed = process_notification_job(job)
            if processed.status == NotificationJob.STATUS_SENT:
                sent += 1
            elif processed.status == NotificationJob.STATUS_FAILED:
                failed += 1
        self.stdout.write(self.style.SUCCESS(f'Processed {len(jobs)} notification job(s): sent={sent}, failed={failed}'))
