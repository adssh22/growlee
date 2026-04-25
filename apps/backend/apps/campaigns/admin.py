from django.contrib import admin

from .models import Campaign, EntryPoint, WheelSegment


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'merchant', 'game_type', 'is_active', 'created_at')
    search_fields = ('name', 'merchant__name')
    list_filter = ('game_type', 'is_active')


@admin.register(EntryPoint)
class EntryPointAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'merchant', 'campaign', 'channel', 'placement')
    search_fields = ('name', 'code', 'merchant__name')
    list_filter = ('channel',)


@admin.register(WheelSegment)
class WheelSegmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'label', 'campaign', 'reward', 'probability_weight', 'daily_quota', 'active')
    search_fields = ('label', 'campaign__name', 'campaign__merchant__name')
    list_filter = ('active',)
