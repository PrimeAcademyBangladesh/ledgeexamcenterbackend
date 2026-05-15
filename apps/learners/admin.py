"""
Django admin for the Learners app.

Operational notes:
- ReasonableAdjustment must be Accepted OR Denied at all times (DB constraint
  reasonable_adjustment_must_be_accepted_or_denied) — there's no "pending"
  state. The admin form will reject saves that leave both off.
- Enrollment lifecycle fields (enrolled_at, withdrawn_at, completed_at) are
  read-only — status transitions go through the model, not free-form edit.
- raw_id_fields / autocomplete_fields keep the change list fast on big
  learner sets.
"""
from django.contrib import admin

from .models import Enrollment, ReasonableAdjustment


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "learner",
        "qualification",
        "cohort",
        "employer",
        "status",
        "enrolled_at",
        "expected_end_date",
    )
    list_filter = ("status", "qualification", "cohort")
    search_fields = (
        "learner__learner_id",
        "learner__user__first_name",
        "learner__user__last_name",
        "learner__user__email",
        "qualification__title",
        "qualification__code",
        "cohort",
        "employer",
    )
    list_select_related = ("learner__user", "qualification")
    autocomplete_fields = ("learner", "qualification")
    date_hierarchy = "enrolled_at"
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        ("Identity", {
            "fields": ("id", "learner", "qualification", "cohort", "employer"),
        }),
        ("Lifecycle", {
            "fields": (
                "status",
                "enrolled_at",
                "expected_end_date",
                "completed_at",
                "withdrawn_at",
                "withdrawal_reason",
            ),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
        }),
    )


# ---------------------------------------------------------------------------
# ReasonableAdjustment
# ---------------------------------------------------------------------------
@admin.register(ReasonableAdjustment)
class ReasonableAdjustmentAdmin(admin.ModelAdmin):
    list_display = (
        "learner",
        "state_label",
        "extra_time_minutes",
        "created_by",
        "created_at",
    )
    list_filter = ("accepted", "denied")
    search_fields = (
        "learner__learner_id",
        "learner__user__first_name",
        "learner__user__last_name",
        "learner__user__email",
        "notes",
        "denial_reason",
    )
    list_select_related = ("learner__user", "created_by")
    autocomplete_fields = ("learner", "created_by")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        ("Request", {
            "fields": ("id", "learner", "notes", "created_by"),
        }),
        ("Decision", {
            "fields": ("accepted", "denied", "denial_reason", "extra_time_minutes"),
            "description": (
                "Each adjustment must be Accepted OR Denied — never both, never "
                "neither. If Denied, a reason is required."
            ),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="State", ordering="accepted")
    def state_label(self, obj):
        if obj.accepted:
            return "Accepted"
        if obj.denied:
            return "Denied"
        return "—"
