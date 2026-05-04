from django.db import models
from django.utils import timezone

from apps.merchants.models import Merchant


class Campaign(models.Model):
    GAME_TYPES = [
        ('spin', 'Roue'),
        ('scratch', 'Ticket à gratter'),
        ('quiz', 'Quiz'),
    ]
    JOURNEY_TYPES = [
        ('premium_mobile', 'Mobile premium'),
        ('growly_reference', 'Growly référence'),
        ('street_food', 'Street food / Kebab'),
        ('trattoria', 'Restaurant italien'),
        ('padel_arena', 'Sport / Padel'),
        ('compact', 'Compact'),
    ]

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='campaigns')
    name = models.CharField(max_length=120)
    game_type = models.CharField(max_length=20, choices=GAME_TYPES, default='spin')
    reward_label = models.CharField(max_length=180, default='-10% sur votre prochaine visite')
    quiz_question = models.CharField(max_length=220, default='Quelle offre préférez-vous aujourd’hui ?')
    quiz_answer_a = models.CharField(max_length=120, default='Un café offert')
    quiz_answer_b = models.CharField(max_length=120, default='Un dessert maison')
    quiz_answer_c = models.CharField(max_length=120, default='-10% sur l’addition')
    scratch_label = models.CharField(max_length=120, default='Grattez ici')
    landing_headline = models.CharField(max_length=160, default='Tentez votre chance')
    landing_subheadline = models.CharField(max_length=255, default='Un jeu rapide pour découvrir votre surprise du jour.')
    cta_label = models.CharField(max_length=80, default='Jouer maintenant')
    journey_type = models.CharField(max_length=40, choices=JOURNEY_TYPES, default='premium_mobile')
    review_enabled = models.BooleanField(default=True)
    wallet_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    send_immediately = models.BooleanField(default=True)
    scheduled_for = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.merchant.name} · {self.name}'


class EntryPoint(models.Model):
    CHANNELS = [
        ('qr', 'QR Code'),
        ('nfc', 'NFC'),
        ('hybrid', 'QR + NFC'),
    ]

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='entry_points')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='entry_points')
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=120, unique=True)
    channel = models.CharField(max_length=20, choices=CHANNELS, default='qr')
    placement = models.CharField(max_length=120, default='counter')
    redirect_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def target_url(self):
        if self.redirect_url:
            return self.redirect_url
        return f'/play/{self.merchant.slug}/'

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.merchant.name} · {self.name}'


class WheelSegment(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='wheel_segments')
    reward = models.ForeignKey('rewards.Reward', on_delete=models.SET_NULL, null=True, blank=True, related_name='wheel_segments')
    label = models.CharField(max_length=120)
    probability_weight = models.PositiveIntegerField(default=10)
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    daily_quota = models.PositiveIntegerField(default=100)
    color = models.CharField(max_length=20, default='#f59e0b')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f'{self.campaign.name} · {self.label}'
