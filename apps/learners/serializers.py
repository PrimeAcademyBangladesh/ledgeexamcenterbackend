"""
apps/learners/serializers.py
────────────────────────────────────────────────────────────
camelCase out / snake_case in — matches the React types in
src/services/api/types.ts (Learner, Enrollment, ReasonableAdjustment,
RegisterLearnerRequest).
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import RegexValidator
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.users.models import User, LearnerProfile, Role
from apps.qualifications.models import Qualification
from apps.exams.models import ExamConfig
from apps.exams.services import create_scheduled_session

from .models import (
    Enrollment,
    EnrollmentStatus,
    ReasonableAdjustment,
    validate_reasonable_adjustment_state,
)


uln_validator = RegexValidator(r"^\d{10}$", "ULN must be exactly 10 digits.")


# ─────────────────────────────────────────────────────────────
# READ — Learner row (AdminLearners table + view modal)
# ─────────────────────────────────────────────────────────────

class LearnerSerializer(serializers.ModelSerializer):
    """
    Mirrors `Learner` in src/services/api/types.ts.
    """
    id = serializers.UUIDField(source="user.id", read_only=True)
    firstName = serializers.CharField(source="user.first_name", read_only=True)
    lastName = serializers.CharField(source="user.last_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    isActive = serializers.BooleanField(source="user.is_active", read_only=True)
    createdAt = serializers.DateTimeField(source="user.date_joined", read_only=True)

    learnerId = serializers.CharField(source="learner_id", read_only=True)
    uln = serializers.CharField(read_only=True)
    dateOfBirth = serializers.DateField(source="date_of_birth", read_only=True)
    phone = serializers.CharField(read_only=True)
    photo = serializers.SerializerMethodField()
    idVerified = serializers.BooleanField(source="id_verified", read_only=True)

    # Most-recent active enrollment — UI shows "Qualification" column
    qualificationId = serializers.SerializerMethodField()
    qualificationName = serializers.SerializerMethodField()

    class Meta:
        model = LearnerProfile
        fields = [
            "id", "learnerId", "firstName", "lastName", "email", "uln",
            "dateOfBirth", "phone", "photo", "idVerified", "isActive",
            "qualificationId", "qualificationName", "createdAt",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_photo(self, obj) -> str | None:
        return obj.photo.url if obj.photo else None

    def _active_enrollment(self, obj):
        return obj.enrollments.filter(status=EnrollmentStatus.ACTIVE).select_related("qualification").first()

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_qualificationId(self, obj) -> str | None:
        e = self._active_enrollment(obj)
        return str(e.qualification_id) if e else None

    @extend_schema_field(serializers.CharField())
    def get_qualificationName(self, obj) -> str:
        e = self._active_enrollment(obj)
        return e.qualification.title if e else ""


# ─────────────────────────────────────────────────────────────
# READ — Learner detail (single learner view modal)
# ─────────────────────────────────────────────────────────────

class _NestedEnrollmentSerializer(serializers.Serializer):
    """Read-only nested view of an Enrollment for the learner detail page."""
    id = serializers.UUIDField()
    qualificationId = serializers.UUIDField(source="qualification_id")
    qualificationName = serializers.CharField(source="qualification.title")
    qualificationCode = serializers.CharField(source="qualification.code")
    cohort = serializers.CharField()
    employer = serializers.CharField()
    status = serializers.CharField()
    enrolledAt = serializers.DateTimeField(source="enrolled_at")
    expectedEndDate = serializers.DateField(source="expected_end_date", allow_null=True)
    completedAt = serializers.DateTimeField(source="completed_at", allow_null=True)
    withdrawnAt = serializers.DateTimeField(source="withdrawn_at", allow_null=True)
    withdrawalReason = serializers.CharField(source="withdrawal_reason", allow_blank=True)


class _NestedExamSessionSerializer(serializers.Serializer):
    """Read-only nested view of an ExamSession for the learner detail page."""
    id = serializers.UUIDField()
    examConfigId = serializers.UUIDField(source="exam_config_id")
    examTitle = serializers.CharField(source="exam_config.title")
    scheduledDate = serializers.DateField(source="scheduled_date")
    scheduledTime = serializers.TimeField(source="scheduled_time")
    invigilatorId = serializers.UUIDField(source="invigilator_id")
    invigilatorName = serializers.SerializerMethodField()
    pin = serializers.CharField()
    pinActive = serializers.BooleanField(source="pin_active")
    pinWindowStart = serializers.DateTimeField(source="pin_window_start", allow_null=True)
    pinWindowEnd = serializers.DateTimeField(source="pin_window_end", allow_null=True)
    allowImmediateStart = serializers.BooleanField(source="allow_immediate_start")
    status = serializers.CharField()
    idVerified = serializers.BooleanField(source="id_verified")
    completedSuccessfully = serializers.BooleanField(source="completed_successfully", allow_null=True)
    extraTimeMinutes = serializers.IntegerField(source="extra_time_minutes", allow_null=True)
    startedAt = serializers.DateTimeField(source="started_at", allow_null=True)
    submittedAt = serializers.DateTimeField(source="submitted_at", allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at")

    @extend_schema_field(serializers.CharField())
    def get_invigilatorName(self, obj) -> str:
        u = obj.invigilator
        return f"{u.first_name} {u.last_name}".strip()


class _NestedReasonableAdjustmentSerializer(serializers.Serializer):
    """Read-only nested RA row."""
    id = serializers.UUIDField()
    notes = serializers.CharField()
    accepted = serializers.BooleanField()
    denied = serializers.BooleanField()
    denialReason = serializers.CharField(source="denial_reason", allow_blank=True)
    extraTimeMinutes = serializers.IntegerField(source="extra_time_minutes")
    createdAt = serializers.DateTimeField(source="created_at")


class LearnerDetailSerializer(LearnerSerializer):
    """
    Used only by GET /learner/learners/{id}/.
    Adds every related entity (enrollments, exam sessions, reasonable
    adjustments) read-only so the admin's view modal has a single round-trip.
    """
    idDocument = serializers.SerializerMethodField()
    enrollments = _NestedEnrollmentSerializer(many=True, read_only=True)
    examSessions = serializers.SerializerMethodField()
    reasonableAdjustments = _NestedReasonableAdjustmentSerializer(
        many=True, read_only=True, source="reasonable_adjustments",
    )

    class Meta(LearnerSerializer.Meta):
        fields = LearnerSerializer.Meta.fields + [
            "idDocument", "enrollments", "examSessions", "reasonableAdjustments",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_idDocument(self, obj) -> str | None:
        return obj.id_document.url if obj.id_document else None

    @extend_schema_field(_NestedExamSessionSerializer(many=True))
    def get_examSessions(self, obj):
        # FK lives on User, not LearnerProfile.
        sessions = obj.user.exam_sessions_as_learner.all()
        return _NestedExamSessionSerializer(sessions, many=True, context=self.context).data


# ─────────────────────────────────────────────────────────────
# WRITE — Register Learner (AdminLearners modal)
# ─────────────────────────────────────────────────────────────

class RegisterLearnerSerializer(serializers.Serializer):
    """
    Mirrors `RegisterLearnerRequest` in src/services/api/types.ts.

    One atomic POST creates: User → LearnerProfile (ULN set) →
    Enrollment → ExamSession (with PIN window).
    """
    # ----- learner identity -----
    firstName = serializers.CharField(source="first_name", max_length=80)
    lastName = serializers.CharField(source="last_name", max_length=80)
    email = serializers.EmailField()
    uln = serializers.CharField(validators=[uln_validator])
    password = serializers.CharField(write_only=True, min_length=8)
    dateOfBirth = serializers.DateField(source="date_of_birth", required=False, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)

    # ----- enrollment -----
    qualificationId = serializers.UUIDField(source="qualification_id")
    cohort = serializers.CharField(required=False, allow_blank=True, max_length=40)
    employer = serializers.CharField(required=False, allow_blank=True, max_length=200)

    # ----- first exam session -----
    knowledgeTestId = serializers.UUIDField(source="exam_config_id")
    invigilatorId = serializers.UUIDField(source="invigilator_id")
    testDate = serializers.DateField(source="scheduled_date")
    testTime = serializers.TimeField(source="scheduled_time")
    allowImmediateStart = serializers.BooleanField(source="allow_immediate_start", default=False)
    pin = serializers.RegexField(r"^\d{6}$")

    # ----- validation -----
    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_uln(self, value):
        if LearnerProfile.objects.filter(uln=value).exists():
            raise serializers.ValidationError("ULN already in use.")
        return value

    def validate_qualificationId(self, value):
        if not Qualification.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError("Qualification not found or inactive.")
        return value

    def validate_knowledgeTestId(self, value):
        if not ExamConfig.objects.filter(pk=value, status="published").exists():
            raise serializers.ValidationError("Knowledge test not found or unpublished.")
        return value

    def validate_invigilatorId(self, value):
        if not User.objects.filter(pk=value, role=Role.INVIGILATOR, is_active=True).exists():
            raise serializers.ValidationError("Invigilator not found or inactive.")
        return value

    @transaction.atomic
    def create(self, validated):
        password = validated.pop("password")
        uln = validated.pop("uln")
        qualification_id = validated.pop("qualification_id")
        cohort = validated.pop("cohort", "") or "default"
        employer = validated.pop("employer", "") or ""
        date_of_birth = validated.pop("date_of_birth", None)
        phone = validated.pop("phone", "") or ""

        exam_config_id = validated.pop("exam_config_id")
        invigilator_id = validated.pop("invigilator_id")
        scheduled_date = validated.pop("scheduled_date")
        scheduled_time = validated.pop("scheduled_time")
        allow_immediate_start = validated.pop("allow_immediate_start", False)
        pin = validated.pop("pin")

        user = User.objects.create_user(
            email=validated["email"],
            password=password,
            first_name=validated["first_name"],
            last_name=validated["last_name"],
            role=Role.LEARNER,
        )
        profile = user.learner_profile
        profile.uln = uln
        if date_of_birth:
            profile.date_of_birth = date_of_birth
        if phone:
            profile.phone = phone
        profile.save()

        # 2. Enrollment
        Enrollment.objects.create(
            learner=profile,
            qualification_id=qualification_id,
            cohort=cohort,
            employer=employer,
        )

        # 3. First scheduled ExamSession (PIN window = scheduled - 5min,
        #    or now() if allow_immediate_start). Re-raises on any failure
        #    so the whole atomic block rolls back — no orphan learners.
        exam_config = ExamConfig.objects.get(pk=exam_config_id)
        invigilator = User.objects.get(pk=invigilator_id)
        create_scheduled_session(
            exam_config=exam_config,
            learner=user,
            invigilator=invigilator,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            pin=pin,
            allow_immediate_start=allow_immediate_start,
        )

        return profile



class LearnerDropDownSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for dropdowns, etc. where we just need the learner's
    name and ID.
    """
    id = serializers.UUIDField(source="user.id", read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = LearnerProfile
        fields = ["id", "name"]

    def get_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    


# ─────────────────────────────────────────────────────────────
# WRITE — Update Learner (PATCH)
# ─────────────────────────────────────────────────────────────

class UpdateLearnerSerializer(serializers.Serializer):
    """
    Admin edit dialog. ULN is intentionally NOT here — it is a permanent
    UK identifier and must never be rewritten after issue. Any `uln` key
    in the request body is silently dropped by DRF.
    """
    firstName = serializers.CharField(source="first_name", required=False)
    lastName = serializers.CharField(source="last_name", required=False)
    email = serializers.EmailField(required=False)
    dateOfBirth = serializers.DateField(source="date_of_birth", required=False, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)

    def validate_email(self, value):
        value = value.lower()
        qs = User.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("Email already in use.")
        return value

    @transaction.atomic
    def update(self, profile, validated):
        user_fields = {}
        for k in ("first_name", "last_name", "email"):
            if k in validated:
                user_fields[k] = validated.pop(k)
        if user_fields:
            for k, v in user_fields.items():
                setattr(profile.user, k, v)
            profile.user.save()

        for k, v in validated.items():
            setattr(profile, k, v)
        profile.save()
        return profile


# ─────────────────────────────────────────────────────────────
# Enrollment serializers
# ─────────────────────────────────────────────────────────────

class EnrollmentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    learnerId = serializers.UUIDField(source="learner.user_id", read_only=True)
    qualificationId = serializers.UUIDField(source="qualification_id")
    qualificationName = serializers.CharField(source="qualification.title", read_only=True)
    qualificationCode = serializers.CharField(source="qualification.code", read_only=True)
    enrolledAt = serializers.DateTimeField(source="enrolled_at", read_only=True)
    expectedEndDate = serializers.DateField(source="expected_end_date", required=False, allow_null=True)
    completedAt = serializers.DateTimeField(source="completed_at", read_only=True)
    withdrawnAt = serializers.DateTimeField(source="withdrawn_at", read_only=True)
    withdrawalReason = serializers.CharField(source="withdrawal_reason", required=False, allow_blank=True)

    class Meta:
        model = Enrollment
        fields = [
            "id", "learnerId", "qualificationId", "qualificationName", "qualificationCode",
            "cohort", "employer", "status", "enrolledAt", "expectedEndDate",
            "completedAt", "withdrawnAt", "withdrawalReason",
        ]


class CreateEnrollmentSerializer(serializers.Serializer):
    learnerId = serializers.UUIDField(source="learner_user_id")
    qualificationId = serializers.UUIDField(source="qualification_id")
    cohort = serializers.CharField(max_length=40)
    employer = serializers.CharField(required=False, allow_blank=True, max_length=200)
    expectedEndDate = serializers.DateField(source="expected_end_date", required=False, allow_null=True)

    def create(self, validated):
        learner_user_id = validated.pop("learner_user_id")
        try:
            profile = LearnerProfile.objects.get(user_id=learner_user_id)
        except LearnerProfile.DoesNotExist:
            raise serializers.ValidationError({"learnerId": "Learner not found."})
        return Enrollment.objects.create(learner=profile, **validated)


# ─────────────────────────────────────────────────────────────
# Reasonable Adjustment serializers
# ─────────────────────────────────────────────────────────────

class ReasonableAdjustmentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    learnerId = serializers.UUIDField(source="learner.user_id", read_only=True)
    learnerName = serializers.SerializerMethodField()
    notes = serializers.CharField()
    accepted = serializers.BooleanField()
    denied = serializers.BooleanField()
    denialReason = serializers.CharField(source="denial_reason", required=False, allow_blank=True)
    extraTimeMinutes = serializers.IntegerField(source="extra_time_minutes", required=False, min_value=0, max_value=240)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = ReasonableAdjustment
        fields = [
            "id", "learnerId", "learnerName", "notes",
            "accepted", "denied", "denialReason", "extraTimeMinutes", "createdAt",
        ]

    @extend_schema_field(serializers.CharField())
    def get_learnerName(self, obj) -> str:
        return obj.learner.user.full_name

    def validate(self, attrs):
        instance = self.instance

        def pick(field):
            if field in attrs:
                return attrs[field]
            return getattr(instance, field, None)

        try:
            validate_reasonable_adjustment_state(
                accepted=pick("accepted"),
                denied=pick("denied"),
                denial_reason=pick("denial_reason"),
            )
        except DjangoValidationError as exc:
            errors = exc.message_dict
            if "denial_reason" in errors:
                errors["denialReason"] = errors.pop("denial_reason")
            raise serializers.ValidationError(errors)
        return attrs


class CreateReasonableAdjustmentSerializer(serializers.Serializer):
    learnerId = serializers.UUIDField()
    notes = serializers.CharField()
    accepted = serializers.BooleanField(default=False)
    denied = serializers.BooleanField(default=False)
    denialReason = serializers.CharField(source="denial_reason", required=False, allow_blank=True)
    extraTimeMinutes = serializers.IntegerField(source="extra_time_minutes", default=0, min_value=0, max_value=240)

    def validate(self, attrs):
        try:
            validate_reasonable_adjustment_state(
                accepted=attrs.get("accepted"),
                denied=attrs.get("denied"),
                denial_reason=attrs.get("denial_reason"),
            )
        except DjangoValidationError as exc:
            errors = exc.message_dict
            if "denial_reason" in errors:
                errors["denialReason"] = errors.pop("denial_reason")
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated):
        learner_user_id = validated.pop("learnerId")
        try:
            profile = LearnerProfile.objects.get(user_id=learner_user_id)
        except LearnerProfile.DoesNotExist:
            raise serializers.ValidationError({"learnerId": "Learner not found."})
        request = self.context.get("request")
        return ReasonableAdjustment.objects.create(
            learner=profile,
            created_by=getattr(request, "user", None) if request and request.user.is_authenticated else None,
            **validated,
        )
