"""
Serializers — DRF.

NOTE: snake_case fields here are converted to camelCase at the API boundary
either by djangorestframework-camel-case OR by the React Axios interceptor.
Do not enable both at the same time.
"""

import calendar as _cal

from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers
from django.utils import timezone


def _add_months(dt, months):
    """Return dt shifted forward by `months` calendar months."""
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    day = min(dt.day, _cal.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)

from apps.qualifications.models import Qualification
from apps.questions.models import Question, Scenario
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
            "grade_boundaries", "scenario_rules",
            "cert_validity_months",
            "status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "qualification_title"]
        extra_kwargs = {
            "cert_validity_months": {"required": False, "allow_null": True},
        }

    def validate_scenario_rules(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("scenario_rules must be a list.")
        for rule in value:
            if not isinstance(rule, dict):
                raise serializers.ValidationError("Each rule must be an object.")
            if not isinstance(rule.get("count"), int) or rule["count"] < 1:
                raise serializers.ValidationError("Each rule must have count >= 1.")
            if not isinstance(rule.get("questions_per_scenario"), int) or rule["questions_per_scenario"] < 1:
                raise serializers.ValidationError("Each rule must have questions_per_scenario >= 1.")
        return value

    def validate(self, attrs):
        gb = attrs.pop("grade_boundaries", None) if "grade_boundaries" in attrs else None
        if gb:
            attrs.update(gb)
        if attrs.get("grade_pass") is not None and attrs.get("grade_merit") is not None and attrs.get("grade_distinction") is not None:
            if not (attrs["grade_pass"] < attrs["grade_merit"] < attrs["grade_distinction"]):
                raise serializers.ValidationError("Pass < Merit < Distinction is required")
        # Validate scenario_rules total does not exceed questions_per_exam
        scenario_rules = attrs.get("scenario_rules") or []
        questions_per_exam = attrs.get("questions_per_exam")
        if scenario_rules and questions_per_exam is not None:
            scenario_total = sum(r["count"] * r["questions_per_scenario"] for r in scenario_rules)
            if scenario_total > questions_per_exam:
                raise serializers.ValidationError(
                    f"Scenario rules total ({scenario_total}) exceeds questions_per_exam ({questions_per_exam})."
                )
        return attrs


class ExamConfigDropdownSerializer(serializers.ModelSerializer):
    qualification_id = serializers.UUIDField(read_only=True)
    qualification_title = serializers.CharField(source="qualification.title", read_only=True)

    class Meta:
        model = ExamConfig
        fields = [
            "id",
            "title",
            "qualification_id",
            "qualification_title",
            "version_number",
            "exam_type",
            "status",
        ]



# ---------------------------------------------------------------------------
# Scenario (admin-facing)
# ---------------------------------------------------------------------------
class ScenarioSerializer(serializers.ModelSerializer):
    qualification_id = serializers.PrimaryKeyRelatedField(
        queryset=Qualification.objects.all(),
        source="qualification",
    )
    qualification_title = serializers.CharField(source="qualification.title", read_only=True)
    question_count = serializers.IntegerField(source="active_question_count", read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Scenario
        fields = [
            "id", "title", "body",
            "qualification_id", "qualification_title",
            "image", "image_url",
            "status", "question_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "question_count", "image_url", "created_at", "updated_at", "qualification_title"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image_url(self, obj) -> str | None:
        if not obj.image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


# ---------------------------------------------------------------------------
# ExamQuestion (learner-safe — NO correct_answers, NO explanation)
# ---------------------------------------------------------------------------
class ExamQuestionSerializer(serializers.ModelSerializer):
    questionText = serializers.CharField(source="question_text", read_only=True)
    questionType = serializers.CharField(source="question_type", read_only=True)
    imageUrl = serializers.SerializerMethodField()
    scenarioId = serializers.UUIDField(source="scenario_id", read_only=True, allow_null=True)

    class Meta:
        model = Question
        fields = ["id", "questionText", "questionType", "options", "imageUrl", "scenarioId"]

    def get_imageUrl(self, obj):
        if not obj.image_qs:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.image_qs.url)
        return obj.image_qs.url


# ---------------------------------------------------------------------------
# ExamSession
# ---------------------------------------------------------------------------
class ExamSessionSerializer(serializers.ModelSerializer):
    enrollment_id = serializers.UUIDField(read_only=True, allow_null=True)
    exam_title = serializers.CharField(source="exam_config.title", read_only=True)
    qualification_id = serializers.UUIDField(source="exam_config.qualification_id", read_only=True)
    qualification_title = serializers.CharField(source="exam_config.qualification.title", read_only=True)
    learner_name = serializers.SerializerMethodField()
    learner_uln = serializers.SerializerMethodField()
    invigilator_name = serializers.SerializerMethodField()
    question_ids = serializers.JSONField(source="question_set", read_only=True)

    class Meta:
        model = ExamSession
        fields = [
            "id",
            "enrollment_id",
            "exam_config_id", "exam_title", "qualification_id", "qualification_title",
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

    @extend_schema_field(serializers.CharField(allow_blank=True, allow_null=True))
    def get_learner_uln(self, obj) -> str:
        profile = getattr(obj.learner, "learner_profile", None)
        return profile.uln if profile and profile.uln else ""

    @extend_schema_field(serializers.CharField())
    def get_invigilator_name(self, obj) -> str:
        return f"{obj.invigilator.first_name} {obj.invigilator.last_name}".strip()


class CreateExamSessionSerializer(serializers.Serializer):
    """Payload for POST /api/exams/sessions/ — admin only."""
    enrollment_id = serializers.UUIDField(required=False)
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
    uln = serializers.SerializerMethodField()
    resit_eligible = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_uln(self, obj) -> str:
        profile = getattr(obj.learner, "learner_profile", None)
        return profile.uln if profile and profile.uln else ""

    @extend_schema_field(serializers.BooleanField())
    def get_resit_eligible(self, obj) -> bool:
        from .services import is_resit_eligible
        return is_resit_eligible(obj.score_percent, obj.exam_config.grade_pass)

    violations = IntegrityViolationSerializer(source="session.violations", many=True, read_only=True)
    exam_date = serializers.DateField(read_only=True)
    cert_validity_months = serializers.IntegerField(source="exam_config.cert_validity_months", read_only=True, allow_null=True)
    cert_expiry = serializers.SerializerMethodField()
    completed_successfully = serializers.BooleanField(source="session.completed_successfully", read_only=True, allow_null=True)

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
            "cert_validity_months", "cert_expiry",
            "resit_eligible",
            "completed_successfully",
        ]

    @extend_schema_field(serializers.CharField())
    def get_learner_name(self, obj) -> str:
        return f"{obj.learner.first_name} {obj.learner.last_name}".strip()

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_cert_expiry(self, obj) -> str | None:
        """ISO date the certification expires, or null (no expiry / not configured)."""
        if not obj.passed:
            return None
        months = obj.exam_config.cert_validity_months
        if months is None or months == 0:
            return None
        expiry = _add_months(obj.submitted_at, months)
        return expiry.date().isoformat()


# ---------------------------------------------------------------------------
# Retake Request
# ---------------------------------------------------------------------------
class RetakeRequestSerializer(serializers.ModelSerializer):
    learner_name = serializers.SerializerMethodField()
    exam_title = serializers.CharField(source="exam_config.title", read_only=True)
    qualification_name = serializers.CharField(source="exam_config.qualification.title", read_only=True)
    previous_score = serializers.IntegerField(source="previous_result.score_percent", read_only=True)
    previous_grade = serializers.CharField(source="previous_result.grade", read_only=True)
    resit_eligible = serializers.SerializerMethodField()
    reviewed_by = serializers.UUIDField(source="reviewed_by_id", read_only=True, allow_null=True)
    reviewer_name = serializers.SerializerMethodField()
    new_session_id = serializers.UUIDField(read_only=True)
    scheduled_date = serializers.DateField(source="new_session.scheduled_date", read_only=True, allow_null=True)
    scheduled_time = serializers.TimeField(source="new_session.scheduled_time", read_only=True, allow_null=True)

    class Meta:
        model = RetakeRequest
        fields = [
            "id",
            "learner_id", "learner_name",
            "exam_config_id", "exam_title", "qualification_name",
            "previous_result_id", "previous_score", "previous_grade",
            "resit_eligible",
            "status", "requested_at",
            "reviewed_at", "reviewed_by", "reviewer_name",
            "denial_reason",
            "new_session_id", "scheduled_date", "scheduled_time",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_resit_eligible(self, obj) -> bool:
        from .services import is_resit_eligible
        return is_resit_eligible(obj.previous_result.score_percent, obj.exam_config.grade_pass)

    @extend_schema_field(serializers.CharField())
    def get_learner_name(self, obj) -> str:
        return f"{obj.learner.first_name} {obj.learner.last_name}".strip()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_reviewer_name(self, obj) -> str | None:
        if not obj.reviewed_by:
            return None
        return f"{obj.reviewed_by.first_name} {obj.reviewed_by.last_name}".strip()


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


class RescheduleExamSessionSerializer(serializers.Serializer):
    """Payload for PATCH /api/exams/sessions/{id}/reschedule/ — admin only."""
    exam_config_id = serializers.UUIDField()
    invigilator_id = serializers.UUIDField()
    scheduled_date = serializers.DateField()
    scheduled_time = serializers.TimeField()
    pin = serializers.RegexField(r"^\d{6}$", required=False)
