from django.contrib import admin

from .models import Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = [
        "short_text", "qualification", "question_type",
        "option_count", "is_active", "created_at", "created_by",
    ]
    list_filter = ["question_type", "is_active", "qualification__sector", "created_at"]
    search_fields = ["question_text", "tags", "qualification__title", "qualification__code"]
    autocomplete_fields = ["qualification"]
    readonly_fields = ["id", "created_at", "updated_at", "created_by"]
    ordering = ["-created_at"]
    list_per_page = 50
    list_select_related = ["qualification", "qualification__sector", "created_by"]

    fieldsets = [
        ("Question", {
            "fields": ["id", "qualification", "question_type", "question_text", "image_qs"],
        }),
        ("Answer", {
            "fields": ["options", "correct_answers", "explanation"],
        }),
        ("Meta", {
            "fields": ["tags", "is_active", "created_by", "created_at", "updated_at"],
        }),
    ]

    def short_text(self, obj):
        return obj.question_text[:80] + "…" if len(obj.question_text) > 80 else obj.question_text
    short_text.short_description = "Question"

    def option_count(self, obj):
        return len(obj.options)
    option_count.short_description = "Options"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
