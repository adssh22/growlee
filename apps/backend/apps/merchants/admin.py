from django.contrib import admin

from .models import Merchant


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'slug', 'is_active', 'created_at')
    search_fields = ('name', 'slug')
    list_filter = ('is_active',)
