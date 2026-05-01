from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, LearnerProfile, StaffProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("first_name", "last_name", "email", "role", "is_active", "is_staff", "date_joined")
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("role", "is_active", "is_staff")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
        }),
    )


@admin.register(LearnerProfile)
class LearnerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "learner_id", "uln", "phone")
    search_fields = ("user__email", "user__first_name", "user__last_name")


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "staff_id", "job_title", "staff_id", "phone")
    search_fields = ("user__email", "user__first_name", "user__last_name")
