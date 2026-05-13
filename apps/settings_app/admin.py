from django.contrib import admin

from .models import SettingsAuditLog, SystemSettings


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    readonly_fields = ("updated_at", "updated_by")
    fieldsets = (
        (
            "Organisation",
            {
                "fields": ("org_name", "support_email", "org_website", "logo_url"),
            },
        ),
        (
            "Default Grade Boundaries",
            {
                "fields": (
                    "default_pass_boundary",
                    "default_merit_boundary",
                    "default_distinction_boundary",
                ),
            },
        ),
        (
            "Default Exam Configuration",
            {
                "fields": (
                    "default_time_limit_minutes",
                    "default_questions_per_exam",
                    "default_shuffle_questions",
                    "default_shuffle_options",
                    "default_strict_mode",
                ),
            },
        ),
        (
            "Anti-Cheat & Security",
            {
                "fields": (
                    "max_violations_before_auto_submit",
                    "pin_expiry_minutes_before",
                    "pin_format",
                ),
            },
        ),
        (
            "Mock / Practice Test Settings",
            {
                "fields": (
                    "allow_mock_tests",
                    "show_explanations_on_mock",
                    "show_explanations_on_live",
                ),
            },
        ),
        (
            "Audit",
            {
                "fields": ("updated_at", "updated_by"),
            },
        ),
    )

    def has_add_permission(self, request):
        return not SystemSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SettingsAuditLog)
class SettingsAuditLogAdmin(admin.ModelAdmin):
    list_display = ("changed_at", "field", "changed_by", "old_value", "new_value")
    list_filter = ("field", "changed_at")
    search_fields = ("field", "old_value", "new_value", "changed_by__email")
    readonly_fields = ("changed_at", "changed_by", "field", "old_value", "new_value")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
