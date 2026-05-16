from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.merchants.models import Merchant


class Customer(models.Model):
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='customers')
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True, null=True)
    first_name = models.CharField(max_length=80, blank=True)
    consent_marketing = models.BooleanField(default=False)
    consent_marketing_at = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True, related_name='deleted_customers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('merchant', 'phone')
        ordering = ['-created_at']

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def __str__(self):
        return f'{self.phone} · {self.merchant.name}'


class GameSession(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='game_sessions')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='game_sessions')
    reward_label = models.CharField(max_length=180)
    reward = models.ForeignKey('rewards.Reward', on_delete=models.SET_NULL, null=True, blank=True, related_name='game_sessions')
    claim_code = models.CharField(max_length=32, blank=True)
    claim_token = models.CharField(max_length=64, unique=True, blank=True, null=True)
    is_winner = models.BooleanField(default=True)
    redeemed = models.BooleanField(default=False)
    reward_expires_at = models.DateTimeField(blank=True, null=True)
    reward_available_until = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_recovery_window_open(self):
        from django.utils import timezone
        return bool(self.reward_available_until and self.reward_available_until >= timezone.now())

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.customer.phone} · {self.reward_label}'


class NotificationJob(models.Model):
    CHANNEL_EMAIL = 'email'
    CHANNEL_SMS = 'sms'
    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, 'Email'),
        (CHANNEL_SMS, 'SMS'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='notification_jobs')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='notification_jobs')
    game_session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name='notification_jobs')
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    provider = models.CharField(max_length=80, blank=True, default='')
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    scheduled_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_at', 'id']
        indexes = [
            models.Index(fields=['status', 'scheduled_at']),
            models.Index(fields=['channel']),
            models.Index(fields=['provider']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['game_session', 'channel'], name='uniq_notification_job_session_channel'),
        ]

    def __str__(self):
        return f'{self.get_channel_display()} · {self.game_session_id} · {self.status}'


class WalletPass(models.Model):
    PROVIDERS = [
        ('apple', 'Apple Wallet'),
        ('google', 'Google Wallet'),
    ]
    STATUSES = [
        ('draft', 'Brouillon'),
        ('ready', 'Prêt'),
        ('issued', 'Émis'),
        ('revoked', 'Révoqué'),
        ('error', 'Erreur'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='wallet_passes')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='wallet_passes')
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    serial_number = models.CharField(max_length=80)
    auth_token = models.CharField(max_length=128, blank=True)
    scan_code = models.CharField(max_length=64, unique=True, blank=True, null=True)
    stamps = models.PositiveIntegerField(default=0)
    stamps_target = models.PositiveIntegerField(default=5)
    status = models.CharField(max_length=20, choices=STATUSES, default='draft')
    pass_url = models.URLField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    issued_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('provider', 'serial_number')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_provider_display()} · {self.customer.phone} · {self.status}'
