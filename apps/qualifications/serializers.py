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
from rest_framework import serializers

from .models import (
    Level,
    Qualification,
    QualificationEnrollment,
    QualificationUnit,
    Sector,
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
    class Meta:
        model = Level
        fields = ["id", "name", "numeric_value", "is_active"]
        read_only_fields = ["id"]


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
class QualificationUnitSerializer(serializers.ModelSerializer):
    # `question_count` requires `questions` reverse FK — use annotation when
    # available, fall back to 0 (avoid per-row .count() N+1).
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

    def get_units(self, obj):
        # `units` is prefetched in selectors.qualification_detail_qs — no DB hit.
        units = sorted(obj.units.all(), key=lambda u: u.sort_order)
        return QualificationUnitSerializer(units, many=True).data

    def get_bank_health(self, obj):
        return qualification_bank_health(obj)


class QualificationWriteSerializer(serializers.ModelSerializer):
    sector_id = serializers.PrimaryKeyRelatedField(
        queryset=Sector.objects.only("id", "is_active").filter(is_active=True),
        source="sector", write_only=True,
    )
    level_id = serializers.PrimaryKeyRelatedField(
        queryset=Level.objects.only("id", "is_active").filter(is_active=True),
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

    def validate(self, attrs):
        instance = self.instance

        def pick(field):
            return attrs.get(field, getattr(instance, field, None))

        p, m, d = pick("default_pass_boundary"), pick("default_merit_boundary"), pick("default_distinction_boundary")
        if p is not None and m is not None and d is not None and not (p < m < d):
            raise serializers.ValidationError(
                {"default_merit_boundary": "Grade boundaries must satisfy: pass < merit < distinction."}
            )
        mn, rec = pick("min_bank_size"), pick("recommended_bank_size")
        if mn and rec and mn > rec:
            raise serializers.ValidationError(
                {"min_bank_size": "min_bank_size cannot exceed recommended_bank_size."}
            )
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
