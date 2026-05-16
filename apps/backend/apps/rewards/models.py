from django.conf import settings
from django.db import models

from apps.campaigns.models import Campaign
from apps.merchants.models import Merchant


class Reward(models.Model):
    REWARD_TYPES = [
        ('discount', 'Réduction'),
        ('gift', 'Cadeau'),
        ('free_item', 'Produit offert'),
        ('custom', 'Offre personnalisée'),
    ]

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='rewards')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='rewards', blank=True, null=True)
    name = models.CharField(max_length=120)
    reward_type = models.CharField(max_length=20, choices=REWARD_TYPES, default='custom')
    description = models.CharField(max_length=180)
    probability_weight = models.PositiveIntegerField(default=100)
    daily_quota = models.PositiveIntegerField(default=100)
    total_distributed = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    expires_in_hours = models.PositiveIntegerField(default=168)
    archived_at = models.DateTimeField(blank=True, null=True, db_index=True)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True, related_name='archived_rewards')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['merchant__name', 'name']

    @property
    def is_archived(self):
        return self.archived_at is not None

    def __str__(self):
        return f'{self.merchant.name} · {self.name}'
