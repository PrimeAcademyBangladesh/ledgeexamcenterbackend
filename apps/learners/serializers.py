"""
apps/learners/serializers.py
────────────────────────────────────────────────────────────
camelCase out / snake_case in — matches the React types in
src/services/api/types.ts (Learner, Enrollment, ReasonableAdjustment,
RegisterLearnerRequest).
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.users.models import User, LearnerProfile, Role
from apps.qualifications.models import Qualification
from apps.exams.models import ExamConfig
from apps.exams.services import _compute_pin_window, create_scheduled_session

from .models import (
    Enrollment,
    EnrollmentStatus,
    ReasonableAdjustment,
    validate_reasonable_adjustment_state,
)
from .uln_validator import drf_validate_uln


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
    uln = serializers.CharField(read_only=True, allow_null=True)
    dateOfBirth = serializers.DateField(source="date_of_birth", read_only=True)
    phone = serializers.CharField(read_only=True)
    photo = serializers.SerializerMethodField()
    idVerified = serializers.BooleanField(source="id_verified", read_only=True)

    # Most-recent active enrollment — UI shows "Qualification" column
    qualificationId = serializers.SerializerMethodField()
    qualificationName = serializers.SerializerMethodField()
    cohort = serializers.SerializerMethodField()
    employer = serializers.SerializerMethodField()
    knowledgeTestId = serializers.SerializerMethodField()
    invigilatorId = serializers.SerializerMethodField()
    testDate = serializers.SerializerMethodField()
    testTime = serializers.SerializerMethodField()
    allowImmediateStart = serializers.SerializerMethodField()
    pin = serializers.SerializerMethodField()

    class Meta:
        model = LearnerProfile
        fields = [
            "id", "learnerId", "firstName", "lastName", "email", "uln",
            "dateOfBirth", "phone", "photo", "idVerified", "isActive",
            "qualificationId", "qualificationName", "cohort", "employer",
            "knowledgeTestId", "invigilatorId", "testDate", "testTime",
            "allowImmediateStart", "pin", "createdAt",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_photo(self, obj) -> str | None:
        return obj.photo.url if obj.photo else None

    def _active_enrollment(self, obj):
        return obj.enrollments.filter(status=EnrollmentStatus.ACTIVE).select_related("qualification").first()

    def _scheduled_session(self, obj):
        return (
            obj.user.exam_sessions_as_learner
            .filter(status="scheduled")
            .select_related("exam_config", "invigilator")
            .order_by("scheduled_date", "scheduled_time", "created_at")
            .first()
        )

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_qualificationId(self, obj) -> str | None:
        e = self._active_enrollment(obj)
        return str(e.qualification_id) if e else None

    @extend_schema_field(serializers.CharField())
    def get_qualificationName(self, obj) -> str:
        e = self._active_enrollment(obj)
        return e.qualification.title if e else ""

    @extend_schema_field(serializers.CharField())
    def get_cohort(self, obj) -> str:
        e = self._active_enrollment(obj)
        return e.cohort if e else ""

    @extend_schema_field(serializers.CharField())
    def get_employer(self, obj) -> str:
        e = self._active_enrollment(obj)
        return e.employer if e else ""

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_knowledgeTestId(self, obj) -> str | None:
        session = self._scheduled_session(obj)
        return str(session.exam_config_id) if session else None

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_invigilatorId(self, obj) -> str | None:
        session = self._scheduled_session(obj)
        return str(session.invigilator_id) if session else None

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_testDate(self, obj) -> str | None:
        session = self._scheduled_session(obj)
        return session.scheduled_date.isoformat() if session else None

    @extend_schema_field(serializers.TimeField(allow_null=True))
    def get_testTime(self, obj) -> str | None:
        session = self._scheduled_session(obj)
        return session.scheduled_time.isoformat() if session else None

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_allowImmediateStart(self, obj) -> bool | None:
        session = self._scheduled_session(obj)
        return session.allow_immediate_start if session else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_pin(self, obj) -> str | None:
        session = self._scheduled_session(obj)
        return session.pin if session else None


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

class BlankableDateField(serializers.DateField):
    def to_internal_value(self, value):
        if value in ("", None):
            return None
        return super().to_internal_value(value)


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
    # ULN is issued externally by the UK LRS. Optional: many learners arrive
    # without one. Admin can fill it in later via PATCH.
    uln = serializers.CharField(
        required=False, allow_blank=True, allow_null=True,
        validators=[drf_validate_uln],
    )
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
    testDate = BlankableDateField(source="scheduled_date", required=False, allow_null=True)
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
        # Treat empty string as "no ULN" — return None so it lands as NULL.
        if not value:
            return None
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

    def validate(self, attrs):
        allow_immediate_start = attrs.get("allow_immediate_start", False)
        scheduled_date = attrs.get("scheduled_date")
        if not allow_immediate_start and scheduled_date is None:
            raise serializers.ValidationError({"testDate": "This field is required."})
        if allow_immediate_start and scheduled_date is None:
            attrs["scheduled_date"] = timezone.localdate()
        return attrs

    @transaction.atomic
    def create(self, validated):
        password = validated.pop("password")
        uln = validated.pop("uln", None)
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
        if uln:
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
    Admin edit dialog. ULN is included so admins can add or correct it later
    (e.g. when a learner brings their ULN from another provider). Blank or
    null clears the ULN; otherwise uniqueness is enforced (excluding self).
    """
    firstName = serializers.CharField(source="first_name", required=False)
    lastName = serializers.CharField(source="last_name", required=False)
    email = serializers.EmailField(required=False)
    uln = serializers.CharField(
        required=False, allow_blank=True, allow_null=True,
        validators=[drf_validate_uln],
    )
    dateOfBirth = BlankableDateField(source="date_of_birth", required=False, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    qualificationId = serializers.UUIDField(source="qualification_id", required=False)
    cohort = serializers.CharField(required=False, allow_blank=True, max_length=40)
    employer = serializers.CharField(required=False, allow_blank=True, max_length=200)
    knowledgeTestId = serializers.UUIDField(source="exam_config_id", required=False)
    invigilatorId = serializers.UUIDField(source="invigilator_id", required=False)
    testDate = BlankableDateField(source="scheduled_date", required=False, allow_null=True)
    testTime = serializers.TimeField(source="scheduled_time", required=False)
    allowImmediateStart = serializers.BooleanField(source="allow_immediate_start", required=False)
    pin = serializers.RegexField(r"^\d{6}$", required=False)

    def validate_email(self, value):
        value = value.lower()
        qs = User.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("Email already in use.")
        return value

    def validate_uln(self, value):
        # Empty string ⇒ clear the ULN (store NULL).
        if not value:
            return None
        qs = LearnerProfile.objects.filter(uln=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
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

    def validate(self, attrs):
        allow_immediate_start = attrs.get("allow_immediate_start")
        scheduled_date = attrs.get("scheduled_date", serializers.empty)

        if allow_immediate_start is False and scheduled_date is None:
            raise serializers.ValidationError({"testDate": "This field is required."})

        if allow_immediate_start is True and scheduled_date is None:
            attrs.pop("scheduled_date", None)

        return attrs

    def _latest_enrollment(self, profile):
        return profile.enrollments.order_by("-enrolled_at", "-created_at").first()

    def _get_editable_enrollment(self, profile):
        return (
            profile.enrollments
            .filter(status=EnrollmentStatus.ACTIVE)
            .order_by("-enrolled_at", "-created_at")
            .first()
        )

    def _get_editable_session(self, profile):
        return (
            profile.user.exam_sessions_as_learner
            .filter(status="scheduled")
            .select_related("exam_config", "invigilator")
            .order_by("scheduled_date", "scheduled_time", "created_at")
            .first()
        )

    @transaction.atomic
    def update(self, profile, validated):
        user_fields = {}
        for k in ("first_name", "last_name", "email"):
            if k in validated:
                user_fields[k] = validated.pop(k)
        if user_fields:
            changed_user_fields = []
            for k, v in user_fields.items():
                if getattr(profile.user, k) != v:
                    setattr(profile.user, k, v)
                    changed_user_fields.append(k)
            if changed_user_fields:
                profile.user.save(update_fields=changed_user_fields)

        enrollment_fields = {}
        for k in ("qualification_id", "cohort", "employer"):
            if k in validated:
                enrollment_fields[k] = validated.pop(k)
        if enrollment_fields:
            enrollment = self._get_editable_enrollment(profile)
            if enrollment is None:
                latest_enrollment = self._latest_enrollment(profile)
                if latest_enrollment is not None:
                    raise serializers.ValidationError(
                        {
                            "qualificationId": (
                                f"This learner's enrollment is {latest_enrollment.status} "
                                "and cannot be edited here. Create or reactivate an enrollment instead."
                            )
                        }
                    )
                raise serializers.ValidationError(
                    {"qualificationId": "Enrollment not found for this learner."}
                )
            changed_enrollment_fields = []
            for k, v in enrollment_fields.items():
                if getattr(enrollment, k) != v:
                    setattr(enrollment, k, v)
                    changed_enrollment_fields.append(k)
            if changed_enrollment_fields:
                enrollment.save(update_fields=changed_enrollment_fields)

        session_fields = {}
        for k in (
            "exam_config_id",
            "invigilator_id",
            "scheduled_date",
            "scheduled_time",
            "allow_immediate_start",
            "pin",
        ):
            if k in validated:
                session_fields[k] = validated.pop(k)
        if session_fields:
            session = self._get_editable_session(profile)
            if session is None:
                latest_session = (
                    profile.user.exam_sessions_as_learner
                    .select_related("exam_config", "invigilator")
                    .order_by("-created_at")
                    .first()
                )
                if latest_session is not None:
                    raise serializers.ValidationError(
                        {
                            "knowledgeTestId": (
                                f"This learner's exam session is {latest_session.status} "
                                "and cannot be edited here. Create a new scheduled session instead."
                            )
                        }
                    )
                raise serializers.ValidationError(
                    {"knowledgeTestId": "Scheduled exam session not found for this learner."}
                )

            changed_session_fields = []
            for k, v in session_fields.items():
                if getattr(session, k) != v:
                    setattr(session, k, v)
                    changed_session_fields.append(k)

            if {
                "exam_config_id",
                "scheduled_date",
                "scheduled_time",
                "allow_immediate_start",
            } & set(changed_session_fields):
                pin_start, pin_end = _compute_pin_window(
                    session.scheduled_date,
                    session.scheduled_time,
                    session.exam_config,
                    extra_minutes=session.extra_time_minutes or 0,
                    allow_immediate_start=session.allow_immediate_start,
                )
                session.pin_window_start = pin_start
                session.pin_window_end = pin_end
                changed_session_fields.extend(["pin_window_start", "pin_window_end"])

            if changed_session_fields:
                session.save(update_fields=list(dict.fromkeys(changed_session_fields)))

        changed_profile_fields = []
        for k, v in validated.items():
            if getattr(profile, k) != v:
                setattr(profile, k, v)
                changed_profile_fields.append(k)
        if changed_profile_fields:
            profile.save(update_fields=changed_profile_fields)
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
