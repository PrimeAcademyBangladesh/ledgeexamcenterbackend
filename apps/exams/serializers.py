"""
Serializers — DRF.

NOTE: snake_case fields here are converted to camelCase at the API boundary
either by djangorestframework-camel-case OR by the React Axios interceptor.
Do not enable both at the same time.
"""

from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers
from django.utils import timezone

from apps.qualifications.models import Qualification
from apps.questions.models import Question
from .models import (
    ExamConfig, ExamSession, ExamResult,
    IntegrityViolation, RetakeRequest,
)


# ---------------------------------------------------------------------------
# ExamConfig
# ---------------------------------------------------------------------------
@extend_schema_field(
    inline_serializer(
        name="GradeBoundaries",
        fields={
            "distinction": serializers.IntegerField(),
            "merit": serializers.IntegerField(),
            "pass": serializers.IntegerField(),
        },
    )
)
class GradeBoundariesField(serializers.Field):
    """Flatten/expand grade_distinction|grade_merit|grade_pass <-> {distinction,merit,pass}."""
    def to_representation(self, obj):
        return {
            "distinction": obj.grade_distinction,
            "merit": obj.grade_merit,
            "pass": obj.grade_pass,
        }
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("gradeBoundaries must be an object")
        return {
            "grade_distinction": int(data.get("distinction", 85)),
            "grade_merit": int(data.get("merit", 70)),
            "grade_pass": int(data.get("pass", 60)),
        }


class ExamConfigSerializer(serializers.ModelSerializer):
    qualification_id = serializers.PrimaryKeyRelatedField(
        queryset=Qualification.objects.all(),
        source="qualification",
    )
    qualification_title = serializers.CharField(source="qualification.title", read_only=True)
    grade_boundaries = GradeBoundariesField(source="*")

    class Meta:
        model = ExamConfig
        fields = [
            "id", "title", "version_number",
            "qualification_id", "qualification_title",
            "exam_type", "questions_per_exam", "time_limit_minutes",
            "shuffle_questions", "shuffle_options", "strict_mode",
            "grade_boundaries", "status",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "qualification_title"]

    def validate(self, attrs):
        gb = attrs.pop("grade_boundaries", None) if "grade_boundaries" in attrs else None
        if gb:
            attrs.update(gb)
        if attrs.get("grade_pass") is not None and attrs.get("grade_merit") is not None and attrs.get("grade_distinction") is not None:
            if not (attrs["grade_pass"] < attrs["grade_merit"] < attrs["grade_distinction"]):
                raise serializers.ValidationError("Pass < Merit < Distinction is required")
        return attrs


# ---------------------------------------------------------------------------
# ExamQuestion (learner-safe — NO correct_answers, NO explanation)
# ---------------------------------------------------------------------------
class ExamQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ["id", "question_text", "question_type", "options", "image_qs"]


# ---------------------------------------------------------------------------
# ExamSession
# ---------------------------------------------------------------------------
class ExamSessionSerializer(serializers.ModelSerializer):
    exam_title = serializers.CharField(source="exam_config.title", read_only=True)
    qualification_title = serializers.CharField(source="exam_config.qualification.title", read_only=True)
    learner_name = serializers.SerializerMethodField()
    learner_uln = serializers.CharField(source="learner.uln", read_only=True)
    invigilator_name = serializers.SerializerMethodField()
    question_ids = serializers.JSONField(source="question_set", read_only=True)

    class Meta:
        model = ExamSession
        fields = [
            "id",
            "exam_config_id", "exam_title", "qualification_title",
            "learner_id", "learner_name", "learner_uln",
            "invigilator_id", "invigilator_name",
            "scheduled_date", "scheduled_time",
            "allow_immediate_start",
            "pin_window_start", "pin_window_end",
            "pin", "pin_active",
            "question_ids",
            "status", "id_verified",
            "completed_successfully", "incident_notes",
            "reasonable_adjustments", "extra_time_minutes",
        ]
        read_only_fields = fields  # writes go through dedicated endpoints/serializers

    @extend_schema_field(serializers.CharField())
    def get_learner_name(self, obj) -> str:
        return f"{obj.learner.first_name} {obj.learner.last_name}".strip()

    @extend_schema_field(serializers.CharField())
    def get_invigilator_name(self, obj) -> str:
        return f"{obj.invigilator.first_name} {obj.invigilator.last_name}".strip()


class CreateExamSessionSerializer(serializers.Serializer):
    """Payload for POST /api/exams/sessions/ — admin only."""
    exam_config_id = serializers.UUIDField()
    learner_id = serializers.UUIDField()
    invigilator_id = serializers.UUIDField()
    scheduled_date = serializers.DateField()
    scheduled_time = serializers.TimeField()
    allow_immediate_start = serializers.BooleanField(required=False, default=False)
    pin = serializers.RegexField(r"^\d{6}$", required=False)
    previous_result_id = serializers.UUIDField(required=False)
    reasonable_adjustments = serializers.CharField(required=False, allow_blank=True)
    extra_time_minutes = serializers.IntegerField(required=False, min_value=0)


class UpdateSessionPinSerializer(serializers.Serializer):
    """Payload for PATCH /api/exams/sessions/{id}/pin/ — invigilator/admin only."""
    pin = serializers.RegexField(r"^\d{6}$")


# ---------------------------------------------------------------------------
# Validate PIN  (learner-facing; gateway into the exam runtime)
# ---------------------------------------------------------------------------
class ValidatePinRequestSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    pin = serializers.RegexField(r"^\d{6}$")


class ExamDraftSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    answers = serializers.ListField(child=serializers.DictField())
    current_question_index = serializers.IntegerField(min_value=0)
    flagged_question_indexes = serializers.ListField(child=serializers.IntegerField())
    remaining_seconds = serializers.IntegerField(min_value=0, required=False)
    updated_at = serializers.DateTimeField(required=False)


class ValidatePinResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    exam_questions = ExamQuestionSerializer(many=True, required=False)
    time_limit_minutes = serializers.IntegerField(required=False)
    exam_title = serializers.CharField(required=False)
    qualification_title = serializers.CharField(required=False)
    draft = ExamDraftSerializer(required=False)
    message = serializers.CharField(required=False)


# ---------------------------------------------------------------------------
# Save Draft
# ---------------------------------------------------------------------------
class SaveExamDraftSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    answers = serializers.ListField(child=serializers.DictField())
    current_question_index = serializers.IntegerField(min_value=0)
    flagged_question_indexes = serializers.ListField(child=serializers.IntegerField())
    remaining_seconds = serializers.IntegerField(min_value=0)


# ---------------------------------------------------------------------------
# Submit Exam
# ---------------------------------------------------------------------------
class SubmitExamSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    answers = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField())
    )

    def validate_answers(self, value):
        for a in value:
            if "questionId" not in a or "selected" not in a:
                raise serializers.ValidationError(
                    "Each answer must contain questionId and selected[]"
                )
            if not isinstance(a["selected"], list):
                raise serializers.ValidationError("selected must be an array of integers")
        return value


# ---------------------------------------------------------------------------
# Integrity Violation
# ---------------------------------------------------------------------------
class IntegrityViolationSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrityViolation
        fields = ["type", "detail", "occurred_at", "question_number"]


class ReportViolationSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    violation = IntegrityViolationSerializer()


# ---------------------------------------------------------------------------
# ExamResult
# ---------------------------------------------------------------------------
class ExamResultSerializer(serializers.ModelSerializer):
    learner_name = serializers.SerializerMethodField()
    exam_title = serializers.CharField(source="exam_config.title", read_only=True)
    qualification_id = serializers.UUIDField(source="qualification.id", read_only=True)
    qualification_name = serializers.CharField(source="qualification.title", read_only=True)
    uln = serializers.CharField(source="learner.uln", read_only=True)
    violations = IntegrityViolationSerializer(source="session.violations", many=True, read_only=True)
    exam_date = serializers.DateField(read_only=True)

    class Meta:
        model = ExamResult
        fields = [
            "id",
            "learner_id", "learner_name",
            "exam_config_id", "exam_title",
            "qualification_id", "qualification_name", "uln",
            "score_percent", "correct_count", "total_questions",
            "grade", "passed",
            "time_taken_seconds",
            "violation_count", "violations",
            "question_ids",
            "reasonable_adjustments",
            "invigilator_name",
            "exam_date", "submitted_at",
            "attempt_number",
        ]

    @extend_schema_field(serializers.CharField())
    def get_learner_name(self, obj) -> str:
        return f"{obj.learner.first_name} {obj.learner.last_name}".strip()


# ---------------------------------------------------------------------------
# Retake Request
# ---------------------------------------------------------------------------
class RetakeRequestSerializer(serializers.ModelSerializer):
    learner_name = serializers.SerializerMethodField()
    exam_title = serializers.CharField(source="exam_config.title", read_only=True)
    qualification_name = serializers.CharField(source="exam_config.qualification.title", read_only=True)
    previous_score = serializers.IntegerField(source="previous_result.score_percent", read_only=True)
    previous_grade = serializers.CharField(source="previous_result.grade", read_only=True)
    new_session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = RetakeRequest
        fields = [
            "id",
            "learner_id", "learner_name",
            "exam_config_id", "exam_title", "qualification_name",
            "previous_result_id", "previous_score", "previous_grade",
            "status", "requested_at",
            "reviewed_at", "reviewed_by_id",
            "denial_reason",
            "new_session_id",
        ]

    @extend_schema_field(serializers.CharField())
    def get_learner_name(self, obj) -> str:
        return f"{obj.learner.first_name} {obj.learner.last_name}".strip()


class CreateRetakeRequestSerializer(serializers.Serializer):
    learner_id = serializers.UUIDField()
    exam_config_id = serializers.UUIDField()
    previous_result_id = serializers.UUIDField()


class CreateResitSessionSerializer(serializers.Serializer):
    previous_result_id = serializers.UUIDField()
    invigilator_id = serializers.UUIDField()
    scheduled_date = serializers.DateField(required=False)
    scheduled_time = serializers.TimeField(required=False)


class DenyRetakeSerializer(serializers.Serializer):
    denial_reason = serializers.CharField()
