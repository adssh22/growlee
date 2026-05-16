from django.contrib import admin

from .models import Customer, GameSession, NotificationJob, WalletPass


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('id', 'phone', 'merchant', 'email', 'created_at')
    search_fields = ('phone', 'email', 'merchant__name')


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'campaign', 'reward_label', 'is_winner', 'redeemed', 'created_at')
    list_filter = ('is_winner', 'redeemed')
    search_fields = ('customer__phone', 'campaign__name', 'reward_label')


@admin.register(NotificationJob)
class NotificationJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'merchant', 'customer', 'game_session', 'channel', 'status', 'provider', 'attempts', 'scheduled_at', 'sent_at')
    list_filter = ('channel', 'status', 'provider')
    search_fields = ('customer__phone', 'customer__email', 'merchant__name', 'game_session__claim_code', 'game_session__claim_token')
    readonly_fields = ('created_at', 'updated_at', 'sent_at', 'attempts', 'last_error')
    actions = ('retry_failed',)

    @admin.action(description='Relancer les notifications échouées')
    def retry_failed(self, request, queryset):
        queryset.filter(status=NotificationJob.STATUS_FAILED).update(status=NotificationJob.STATUS_PENDING, last_error='')


@admin.register(WalletPass)
class WalletPassAdmin(admin.ModelAdmin):
    list_display = ('id', 'provider', 'customer', 'campaign', 'status', 'serial_number', 'created_at')
    list_filter = ('provider', 'status')
    search_fields = ('serial_number', 'customer__phone', 'campaign__name')
    readonly_fields = ('payload', 'error_message', 'created_at', 'updated_at')
