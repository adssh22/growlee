from django.contrib import admin

from .models import MerchantMembership


@admin.register(MerchantMembership)
class MerchantMembershipAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'merchant', 'role', 'created_at')
    search_fields = ('user__username', 'user__email', 'merchant__name')
    list_filter = ('role',)
