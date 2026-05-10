"""
apps/qualifications/serializers.py
Lead Edge Ltd EPAO Exam Platform

Performance rules applied here:
    * No DB queries inside SerializerMethodField — all aggregates come
      from queryset annotations (set up in selectors.qualification_*_qs).
    * Bank-health is computed once in selectors.qualification_bank_health
      and reused across the serializer + the @action endpoint.
    * Nested writes use _id PrimaryKeyRelatedField (no extra round-trip
      to fetch the related object before validation).
    * units in detail = prefetch_related, then list-serializer over the
      cached `qualification.units.all()`.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiExample, extend_schema_field, extend_schema_serializer, inline_serializer
from rest_framework import serializers

from .models import (
    Level,
    Qualification,
    QualificationEnrollment,
    QualificationUnit,
    Sector,
    validate_qualification_business_rules,
)
from .selectors import qualification_bank_health

User = get_user_model()


# ────────────────────────────────────────────────────────────
#  Sector
# ────────────────────────────────────────────────────────────
class SectorSerializer(serializers.ModelSerializer):
    qualification_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Sector
        fields = [
            "id", "name", "code", "slug", "sort_order",
            "is_active", "qualification_count",
        ]
        read_only_fields = ["id", "slug", "qualification_count"]


# ────────────────────────────────────────────────────────────
#  Level
# ────────────────────────────────────────────────────────────
class LevelSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="get_name_display", read_only=True)

    class Meta:
        model = Level
        fields = ["id", "label"]
        read_only_fields = fields


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
class QualificationUnitSerializer(serializers.ModelSerializer):
    question_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = QualificationUnit
        fields = [
            "id", "code", "title", "description",
            "weight", "sort_order", "question_count",
        ]
        read_only_fields = ["id", "question_count"]


# ────────────────────────────────────────────────────────────
#  Qualification — list / detail / write split
# ────────────────────────────────────────────────────────────
class QualificationListSerializer(serializers.ModelSerializer):
    """Lean payload — for dropdowns and table rows."""
    sector_name = serializers.CharField(source="sector.name", read_only=True)
    level_name = serializers.CharField(source="level.name", read_only=True)
    question_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Qualification
        fields = [
            "id", "title", "code", "sector_name", "level_name",
            "question_count", "is_active", "created_at",
        ]


class QualificationDetailSerializer(serializers.ModelSerializer):
    """Full record — admin edit + form pre-fill."""
    sector = SectorSerializer(read_only=True)
    level = LevelSerializer(read_only=True)
    units = serializers.SerializerMethodField()
    bank_health = serializers.SerializerMethodField()

    class Meta:
        model = Qualification
        fields = [
            "id", "code", "title", "slug", "description",
            "sector", "level", "is_active",
            "default_questions_per_exam", "default_time_limit_minutes",
            "default_pass_boundary", "default_merit_boundary",
            "default_distinction_boundary",
            "min_bank_size", "recommended_bank_size", "bank_health",
            "resit_unseen_ratio", "resit_fail_margin_percent",
            "max_resit_attempts", "resit_cooldown_days",
            "units", "created_at", "updated_at",
        ]

    @extend_schema_field(QualificationUnitSerializer(many=True))
    def get_units(self, obj):
        # `units` is prefetched in selectors.qualification_detail_qs — no DB hit.
        units = sorted(obj.units.all(), key=lambda u: u.sort_order)
        return QualificationUnitSerializer(units, many=True).data

    @extend_schema_field(
        inline_serializer(
            name="QualificationBankHealthInline",
            fields={
                "current": serializers.IntegerField(),
                "target": serializers.IntegerField(),
                "min": serializers.IntegerField(),
                "percent": serializers.FloatField(),
                "status": serializers.ChoiceField(choices=["healthy", "warning", "critical"]),
            },
        )
    )
    def get_bank_health(self, obj):
        return qualification_bank_health(obj)


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Qualification Create",
            value={
                "code": "L2-CUST-001",
                "title": "Customer Service Practitioner",
                "description": "Level 2 qualification",
                "sector_id": "11111111-1111-1111-1111-111111111111",
                "level_id": "22222222-2222-2222-2222-222222222222",
            },
            request_only=True,
        ),
    ]
)
class QualificationWriteSerializer(serializers.ModelSerializer):
    sector_id = serializers.PrimaryKeyRelatedField(
        queryset=Sector.objects.only("id", "is_active").filter(is_active=True),
        source="sector", write_only=True,
    )
    level_id = serializers.PrimaryKeyRelatedField(
        queryset=Level.objects.only("id"),
        source="level", write_only=True,
    )

    class Meta:
        model = Qualification
        fields = [
            "id", "code", "title", "description",
            "sector_id", "level_id", "is_active",
            "default_questions_per_exam", "default_time_limit_minutes",
            "default_pass_boundary", "default_merit_boundary",
            "default_distinction_boundary",
            "min_bank_size", "recommended_bank_size",
            "resit_unseen_ratio", "resit_fail_margin_percent",
            "max_resit_attempts", "resit_cooldown_days",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "is_active": {"required": False},
            "default_questions_per_exam": {"required": False},
            "default_time_limit_minutes": {"required": False},
            "default_pass_boundary": {"required": False},
            "default_merit_boundary": {"required": False},
            "default_distinction_boundary": {"required": False},
            "min_bank_size": {"required": False},
            "recommended_bank_size": {"required": False},
            "resit_unseen_ratio": {"required": False},
            "resit_fail_margin_percent": {"required": False},
            "max_resit_attempts": {"required": False},
            "resit_cooldown_days": {"required": False},
        }

    def validate(self, attrs):
        instance = self.instance

        def pick(field):
            if field in attrs:
                return attrs[field]
            if instance is not None:
                return getattr(instance, field)
            return self.Meta.model._meta.get_field(field).get_default()

        try:
            validate_qualification_business_rules(
                default_pass_boundary=pick("default_pass_boundary"),
                default_merit_boundary=pick("default_merit_boundary"),
                default_distinction_boundary=pick("default_distinction_boundary"),
                min_bank_size=pick("min_bank_size"),
                recommended_bank_size=pick("recommended_bank_size"),
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return attrs


# ────────────────────────────────────────────────────────────
#  Enrollment — read / write split
# ────────────────────────────────────────────────────────────
class EnrollmentReadSerializer(serializers.ModelSerializer):
    qualification_id = serializers.UUIDField(source="qualification.id", read_only=True)
    qualification_name = serializers.CharField(source="qualification.title", read_only=True)
    qualification_code = serializers.CharField(source="qualification.code", read_only=True)
    learner_id = serializers.UUIDField(source="learner.id", read_only=True)

    class Meta:
        model = QualificationEnrollment
        fields = [
            "id", "learner_id",
            "qualification_id", "qualification_name", "qualification_code",
            "cohort", "employer", "status",
            "enrolled_at", "expected_end_date",
            "completed_at", "withdrawn_at", "withdrawal_reason",
        ]


class EnrollmentWriteSerializer(serializers.ModelSerializer):
    learner_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.only("id", "role").filter(role="learner"),
        source="learner", write_only=True,
    )
    qualification_id = serializers.PrimaryKeyRelatedField(
        queryset=Qualification.objects.only("id", "is_active").filter(is_active=True),
        source="qualification", write_only=True,
    )

    class Meta:
        model = QualificationEnrollment
        fields = [
            "id", "learner_id", "qualification_id",
            "cohort", "employer", "status",
            "enrolled_at", "expected_end_date",
            "withdrawal_reason", "notes",
        ]
        read_only_fields = ["id"]
        validators = []  # uniqueness handled below to give a friendly message

    def validate(self, attrs):
        instance = self.instance
        learner = attrs.get("learner") or getattr(instance, "learner", None)
        qualification = attrs.get("qualification") or getattr(instance, "qualification", None)
        cohort = attrs.get("cohort", getattr(instance, "cohort", ""))

        qs = QualificationEnrollment.objects.filter(
            learner=learner, qualification=qualification, cohort=cohort,
        ).only("id")
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"cohort": "Learner already enrolled on this qualification + cohort."}
            )
        return attrs
