from django.contrib import admin

from .models import (
    Level,
    Qualification,
    QualificationEnrollment,
    QualificationUnit,
    Sector,
)


class QualificationUnitInline(admin.TabularInline):
    model = QualificationUnit
    extra = 0
    fields = ("code", "title", "weight", "sort_order")
    ordering = ("sort_order", "code")


class QualificationEnrollmentInline(admin.TabularInline):
    model = QualificationEnrollment
    extra = 0
    fields = ("learner", "cohort", "status", "enrolled_at", "expected_end_date")
    ordering = ("-enrolled_at",)
    autocomplete_fields = ("learner",)
    show_change_link = True


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "updated_at")
    search_fields = ("name",)
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "sort_order", "is_active", "created_at")
    search_fields = ("name", "code", "slug")
    list_filter = ("is_active",)
    list_editable = ("sort_order", "is_active")
    ordering = ("sort_order", "name")
    readonly_fields = ("slug", "created_at", "updated_at")


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "title",
        "sector",
        "level",
        "is_active",
        "default_questions_per_exam",
        "default_time_limit_minutes",
        "updated_at",
    )
    search_fields = ("code", "title", "slug", "sector__name", "level__name")
    list_filter = ("is_active", "sector", "level", "created_at", "updated_at")
    list_editable = ("is_active",)
    ordering = ("title",)
    autocomplete_fields = ("sector", "level")
    readonly_fields = ("slug", "created_at", "updated_at")
    inlines = (QualificationUnitInline, QualificationEnrollmentInline)
    save_on_top = True

    fieldsets = (
        ("Core Details", {
            "fields": ("code", "title", "slug", "sector", "level", "description", "is_active"),
        }),
        ("Exam Defaults", {
            "fields": (
                "default_questions_per_exam",
                "default_time_limit_minutes",
                "default_pass_boundary",
                "default_merit_boundary",
                "default_distinction_boundary",
            ),
        }),
        ("Question Bank Rules", {
            "fields": ("min_bank_size", "recommended_bank_size"),
        }),
        ("Resit Rules", {
            "fields": (
                "resit_unseen_ratio",
                "resit_fail_margin_percent",
                "max_resit_attempts",
                "resit_cooldown_days",
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("sector", "level")


@admin.register(QualificationUnit)
class QualificationUnitAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "qualification", "weight", "sort_order", "updated_at")
    search_fields = ("code", "title", "qualification__code", "qualification__title")
    list_filter = ("qualification",)
    ordering = ("qualification", "sort_order", "code")
    autocomplete_fields = ("qualification",)
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("qualification")


@admin.register(QualificationEnrollment)
class QualificationEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "learner",
        "qualification",
        "cohort",
        "status",
        "enrolled_at",
        "expected_end_date",
        "completed_at",
    )
    search_fields = (
        "learner__email",
        "learner__first_name",
        "learner__last_name",
        "qualification__code",
        "qualification__title",
        "cohort",
        "employer",
    )
    list_filter = ("status", "qualification", "enrolled_at", "completed_at")
    ordering = ("-enrolled_at",)
    autocomplete_fields = ("learner", "qualification")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Enrollment", {
            "fields": ("learner", "qualification", "cohort", "employer", "status"),
        }),
        ("Dates", {
            "fields": (
                "enrolled_at",
                "expected_end_date",
                "completed_at",
                "withdrawn_at",
            ),
        }),
        ("Notes", {
            "fields": ("withdrawal_reason", "notes"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("learner", "qualification")
