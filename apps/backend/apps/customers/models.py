from django.db import models

from apps.campaigns.models import Campaign
from apps.merchants.models import Merchant


class Customer(models.Model):
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='customers')
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True, null=True)
    first_name = models.CharField(max_length=80, blank=True)
    consent_marketing = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('merchant', 'phone')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.phone} · {self.merchant.name}'


class GameSession(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='game_sessions')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='game_sessions')
    reward_label = models.CharField(max_length=180)
    reward = models.ForeignKey('rewards.Reward', on_delete=models.SET_NULL, null=True, blank=True, related_name='game_sessions')
    claim_code = models.CharField(max_length=32, blank=True)
    is_winner = models.BooleanField(default=True)
    redeemed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.customer.phone} · {self.reward_label}'


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
