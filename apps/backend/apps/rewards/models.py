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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['merchant__name', 'name']

    def __str__(self):
        return f'{self.merchant.name} · {self.name}'
