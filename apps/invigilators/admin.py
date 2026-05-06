from django.contrib import admin

from .models import InvigilatorAvailability, InvigilatorProviderLink, ProviderCentre


@admin.register(ProviderCentre)
class ProviderCentreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "is_active", "created_at")
    list_filter  = ("is_active", "country")
    search_fields = ("name", "code", "city", "postcode")


@admin.register(InvigilatorProviderLink)
class InvigilatorProviderLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "is_primary", "started_at", "ended_at")
    list_filter  = ("is_primary", "provider")
    search_fields = ("user__email", "provider__code")
    autocomplete_fields = ("user", "provider")


@admin.register(InvigilatorAvailability)
class InvigilatorAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("user", "day_of_week", "start_time", "end_time", "is_active")
    list_filter  = ("day_of_week", "is_active")
    search_fields = ("user__email",)
    autocomplete_fields = ("user",)
