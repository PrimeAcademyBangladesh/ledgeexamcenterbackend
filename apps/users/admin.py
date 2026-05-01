from django.contrib import admin
from .models import User, LearnerProfile, StaffProfile


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "email",
        "role",
        "is_active",
        "is_staff",
        "date_joined",
    )
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("role", "is_active", "is_staff")


@admin.register(LearnerProfile)
class LearnerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "learner_id", "uln", "phone")
    search_fields = ("user__email", "user__first_name", "user__last_name")


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "staff_id", "job_title", "staff_id", "phone")
    search_fields = ("user__email", "user__first_name", "user__last_name")
