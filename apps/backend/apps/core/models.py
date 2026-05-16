from django.conf import settings
from django.db import models

from apps.merchants.models import Merchant


class MerchantDailyMetric(models.Model):
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='daily_metrics')
    date = models.DateField()
    scans_count = models.PositiveIntegerField(default=0)
    contacts_count = models.PositiveIntegerField(default=0)
    winners_count = models.PositiveIntegerField(default=0)
    redeemed_count = models.PositiveIntegerField(default=0)
    review_clicks_count = models.PositiveIntegerField(default=0)
    wallet_passes_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'merchant__name']
        constraints = [
            models.UniqueConstraint(fields=['merchant', 'date'], name='uniq_merchant_daily_metric_date'),
        ]
        indexes = [
            models.Index(fields=['merchant']),
            models.Index(fields=['date']),
            models.Index(fields=['merchant', 'date']),
        ]

    def __str__(self):
        return f'{self.merchant} · {self.date}'


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    merchant = models.ForeignKey(Merchant, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=120)
    target_type = models.CharField(max_length=120, blank=True, default='')
    target_id = models.CharField(max_length=120, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant']),
            models.Index(fields=['action']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        target = f' · {self.target_type}:{self.target_id}' if self.target_type or self.target_id else ''
        return f'{self.created_at:%Y-%m-%d %H:%M:%S} · {self.action}{target}'
