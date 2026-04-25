from django.contrib import admin

from .models import Customer, GameSession, WalletPass


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('id', 'phone', 'merchant', 'email', 'created_at')
    search_fields = ('phone', 'email', 'merchant__name')


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'campaign', 'reward_label', 'is_winner', 'redeemed', 'created_at')
    list_filter = ('is_winner', 'redeemed')
    search_fields = ('customer__phone', 'campaign__name', 'reward_label')


@admin.register(WalletPass)
class WalletPassAdmin(admin.ModelAdmin):
    list_display = ('id', 'provider', 'customer', 'campaign', 'status', 'serial_number', 'created_at')
    list_filter = ('provider', 'status')
    search_fields = ('serial_number', 'customer__phone', 'campaign__name')
    readonly_fields = ('payload', 'error_message', 'created_at', 'updated_at')
