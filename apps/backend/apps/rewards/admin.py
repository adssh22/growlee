from django.contrib import admin

from .models import Reward


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'merchant', 'campaign', 'reward_type', 'daily_quota', 'total_distributed', 'active', 'archived_at')
    search_fields = ('name', 'merchant__name', 'campaign__name')
    list_filter = ('reward_type', 'active', 'archived_at')
    readonly_fields = ('archived_at', 'archived_by')
    actions = ('restore_rewards',)

    @admin.action(description='Restaurer les récompenses archivées')
    def restore_rewards(self, request, queryset):
        queryset.update(archived_at=None, archived_by=None)
