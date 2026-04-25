from django.contrib import admin

from .models import Reward


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'merchant', 'campaign', 'reward_type', 'daily_quota', 'total_distributed', 'active')
    search_fields = ('name', 'merchant__name', 'campaign__name')
    list_filter = ('reward_type', 'active')
