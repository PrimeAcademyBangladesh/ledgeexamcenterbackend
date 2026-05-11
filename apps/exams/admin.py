"""
Django admin for the Exams app.

Operational notes:
- Audit fields (timestamps, frozen paper, submitted answers) are read-only —
  results and integrity logs are historical evidence and must not be hand-edited.
- raw_id_fields is used for FKs to User/Question to avoid loading every record
  into a <select>; the picker opens a search popup instead.
- list_select_related cuts N+1 queries on the changelist pages.
"""
from django.contrib import admin

from .models import (
    ExamConfig,
    ExamResult,
    ExamSession,
    IntegrityViolation,
    LearnerSeenQuestion,
    RetakeRequest,
)


# ---------------------------------------------------------------------------
# ExamConfig
# ---------------------------------------------------------------------------
@admin.register(ExamConfig)
class ExamConfigAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "version_number",
        "qualification",
        "exam_type",
        "status",
        "questions_per_exam",
        "time_limit_minutes",
        "updated_at",
    )
    list_filter = ("exam_type", "status", "qualification")
    search_fields = ("title", "version_number", "qualification__title")
    list_select_related = ("qualification",)
    autocomplete_fields = ("qualification",)
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        ("Identity", {
            "fields": ("id", "title", "version_number", "qualification", "exam_type", "status"),
        }),
        ("Paper rules", {
            "fields": ("questions_per_exam", "time_limit_minutes",
                       "shuffle_questions", "shuffle_options", "strict_mode"),
        }),
        ("Grade thresholds", {
            "fields": ("grade_distinction", "grade_merit", "grade_pass"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
        }),
    )


# ---------------------------------------------------------------------------
# Inlines for ExamSession
# ---------------------------------------------------------------------------
class IntegrityViolationInline(admin.TabularInline):
    model = IntegrityViolation
    extra = 0
    fields = ("type", "detail", "question_number", "occurred_at")
    readonly_fields = ("occurred_at",)
    show_change_link = True


class ExamResultInline(admin.StackedInline):
    model = ExamResult
    extra = 0
    can_delete = False
    fk_name = "session"
    fields = (
        "score_percent", "correct_count", "total_questions",
        "grade", "passed", "time_taken_seconds", "violation_count",
        "attempt_number", "exam_date", "submitted_at",
    )
    readonly_fields = fields  # results are immutable from the session view


# ---------------------------------------------------------------------------
# ExamSession
# ---------------------------------------------------------------------------
@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = (
        "exam_config",
        "learner",
        "invigilator",
        "scheduled_date",
        "scheduled_time",
        "status",
        "id_verified",
        "completed_successfully",
    )
    list_filter = ("status", "id_verified", "scheduled_date", "exam_config__exam_type")
    search_fields = (
        "exam_config__title",
        "learner__email", "learner__first_name", "learner__last_name",
        "invigilator__email", "invigilator__first_name", "invigilator__last_name",
        "pin",
    )
    list_select_related = ("exam_config", "learner", "invigilator")
    raw_id_fields = ("learner", "invigilator", "previous_result")
    autocomplete_fields = ("exam_config",)
    date_hierarchy = "scheduled_date"
    ordering = ("-scheduled_date", "-scheduled_time")
    inlines = [IntegrityViolationInline, ExamResultInline]

    readonly_fields = (
        "id", "created_at",
        "question_set", "started_at", "submitted_at",
        "draft_answers", "draft_current_question_index",
        "draft_flagged_question_indexes", "draft_remaining_seconds",
        "draft_updated_at",
    )
    fieldsets = (
        ("Identity", {
            "fields": ("id", "exam_config", "learner", "invigilator", "previous_result"),
        }),
        ("Schedule", {
            "fields": ("scheduled_date", "scheduled_time",
                       "pin_window_start", "pin_window_end", "allow_immediate_start",
                       "pin", "pin_active"),
        }),
        ("Workflow", {
            "fields": ("status", "id_verified", "completed_successfully", "incident_notes"),
        }),
        ("Reasonable adjustments", {
            "fields": ("reasonable_adjustments", "extra_time_minutes"),
        }),
        ("Frozen paper & draft (read-only)", {
            "classes": ("collapse",),
            "fields": ("question_set",
                       "draft_answers", "draft_current_question_index",
                       "draft_flagged_question_indexes", "draft_remaining_seconds",
                       "draft_updated_at",
                       "started_at", "submitted_at"),
        }),
        ("Audit", {
            "fields": ("created_at",),
        }),
    )


# ---------------------------------------------------------------------------
# IntegrityViolation (standalone, plus inline above)
# ---------------------------------------------------------------------------
@admin.register(IntegrityViolation)
class IntegrityViolationAdmin(admin.ModelAdmin):
    list_display = ("session", "type", "question_number", "occurred_at")
    list_filter = ("type", "occurred_at")
    search_fields = ("session__id", "detail")
    list_select_related = ("session",)
    raw_id_fields = ("session",)
    date_hierarchy = "occurred_at"
    readonly_fields = ("id", "occurred_at")


# ---------------------------------------------------------------------------
# ExamResult
# ---------------------------------------------------------------------------
@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = (
        "learner", "exam_config", "qualification",
        "score_percent", "grade", "passed",
        "attempt_number", "exam_date", "submitted_at",
    )
    list_filter = ("grade", "passed", "qualification", "exam_date")
    search_fields = (
        "learner__email", "learner__first_name", "learner__last_name",
        "exam_config__title",
    )
    list_select_related = ("learner", "exam_config", "qualification")
    raw_id_fields = ("session", "learner")
    autocomplete_fields = ("exam_config", "qualification")
    date_hierarchy = "submitted_at"
    # Results are immutable audit records — nothing here should be edited.
    readonly_fields = (
        "id", "session", "learner", "exam_config", "qualification",
        "score_percent", "correct_count", "total_questions",
        "grade", "passed", "time_taken_seconds", "violation_count",
        "question_ids", "answers",
        "invigilator_name", "reasonable_adjustments", "attempt_number",
        "exam_date", "submitted_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# RetakeRequest
# ---------------------------------------------------------------------------
@admin.register(RetakeRequest)
class RetakeRequestAdmin(admin.ModelAdmin):
    list_display = ("learner", "exam_config", "status", "requested_at", "reviewed_at", "reviewed_by")
    list_filter = ("status", "requested_at")
    search_fields = (
        "learner__email", "learner__first_name", "learner__last_name",
        "exam_config__title",
    )
    list_select_related = ("learner", "exam_config", "reviewed_by")
    raw_id_fields = ("learner", "exam_config", "previous_result", "reviewed_by", "new_session")
    date_hierarchy = "requested_at"
    readonly_fields = ("id", "requested_at")


# ---------------------------------------------------------------------------
# LearnerSeenQuestion
# ---------------------------------------------------------------------------
@admin.register(LearnerSeenQuestion)
class LearnerSeenQuestionAdmin(admin.ModelAdmin):
    list_display = ("learner", "qualification", "question", "session", "seen_at")
    list_filter = ("qualification", "seen_at")
    search_fields = (
        "learner__email", "learner__first_name", "learner__last_name",
        "question__id",
    )
    list_select_related = ("learner", "qualification", "question", "session")
    raw_id_fields = ("learner", "qualification", "question", "session")
    date_hierarchy = "seen_at"
    readonly_fields = ("id", "seen_at")

    def has_change_permission(self, request, obj=None):
        # Delivery records are append-only audit data.
        return False
