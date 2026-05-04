from django.contrib.auth.models import User
from django.db import models

from apps.merchants.models import Merchant


class MerchantMembership(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('manager', 'Manager'),
        ('staff', 'Staff'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='merchant_memberships')
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='owner')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'merchant')
        ordering = ['merchant__name', 'user__username']

    def __str__(self):
        return f'{self.user.username} · {self.merchant.name} · {self.role}'


class StaffMFA(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_mfa')
    secret = models.CharField(max_length=64)
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'MFA · {self.user.username} · {"enabled" if self.enabled else "pending"}'
