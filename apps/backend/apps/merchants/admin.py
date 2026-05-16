from django.contrib import admin

from .models import Merchant, Subscription


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'slug', 'is_active', 'subscription_status', 'created_at')
    search_fields = ('name', 'slug')
    list_filter = ('is_active', 'subscription__status', 'subscription__provider', 'subscription__plan')

    def subscription_status(self, obj):
        try:
            return obj.subscription.status
        except Subscription.DoesNotExist:
            return 'legacy'


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'merchant', 'plan', 'status', 'provider', 'provider_customer_id', 'provider_subscription_id', 'updated_at')
    search_fields = ('merchant__name', 'merchant__slug', 'provider_customer_id', 'provider_subscription_id')
    list_filter = ('plan', 'status', 'provider')
    readonly_fields = ('created_at', 'updated_at')
