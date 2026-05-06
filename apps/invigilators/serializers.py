"""
Invigilators app — serializers.

Mirrors the React `Invigilator` and `RegisterInvigilatorRequest` types
from `src/services/api/types.ts`.  All output fields use camelCase via
`source` so the existing Axios layer needs no extra transformation.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from apps.users.models import Role, StaffProfile
from .models import (
    InvigilatorAvailability,
    InvigilatorProviderLink,
    ProviderCentre,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# ProviderCentre
# ---------------------------------------------------------------------------
class ProviderCentreSerializer(serializers.ModelSerializer):
    qualificationCount = serializers.SerializerMethodField()

    class Meta:
        model = ProviderCentre
        fields = [
            "id", "name", "code",
            "contact_email", "contact_phone",
            "address_line1", "address_line2", "city", "postcode", "country",
            "is_active", "notes",
            "created_at", "updated_at",
            "qualificationCount",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_qualificationCount(self, obj) -> int:
        # Number of distinct invigilators currently linked.
        return obj.invigilator_links.filter(ended_at__isnull=True).values("user_id").distinct().count()


# ---------------------------------------------------------------------------
# Invigilator (read) — flattened User + StaffProfile
# ---------------------------------------------------------------------------
class InvigilatorSerializer(serializers.ModelSerializer):
    """
    Output shape matches the frontend `Invigilator` interface:
        { id, firstName, lastName, email, providerCode, isActive, createdAt }
    """
    firstName     = serializers.CharField(source="first_name")
    lastName      = serializers.CharField(source="last_name")
    providerCode  = serializers.SerializerMethodField()
    providerName  = serializers.SerializerMethodField()
    isActive      = serializers.BooleanField(source="is_active")
    createdAt     = serializers.DateTimeField(source="date_joined", read_only=True)
    assignedSessionCount = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "firstName", "lastName", "email",
            "providerCode", "providerName",
            "isActive", "createdAt", "assignedSessionCount",
        ]
        read_only_fields = ["id", "createdAt", "providerName", "assignedSessionCount"]

    # ----- helpers -----
    def _staff_profile(self, obj) -> StaffProfile | None:
        return getattr(obj, "staff_profile", None)

    def get_providerCode(self, obj) -> str:
        sp = self._staff_profile(obj)
        return getattr(sp, "provider_code", "") if sp else ""

    def get_providerName(self, obj) -> str:
        sp = self._staff_profile(obj)
        if not sp or not getattr(sp, "provider_code", ""):
            return ""
        prov = ProviderCentre.objects.filter(code=sp.provider_code).first()
        return prov.name if prov else ""

    def get_assignedSessionCount(self, obj) -> int:
        # Lazy import — avoids circular import with apps.exams.
        try:
            from apps.exams.models import ExamSession
            return ExamSession.objects.filter(invigilator=obj).count()
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# Register Invigilator (write)
# ---------------------------------------------------------------------------
class RegisterInvigilatorSerializer(serializers.Serializer):
    """
    Atomic create:
      1. Creates the User (role=INVIGILATOR)
      2. The post_save signal in apps.users.signals creates StaffProfile
      3. We attach provider_code to StaffProfile
      4. (Optional) creates InvigilatorProviderLink to the matching ProviderCentre
    """
    firstName     = serializers.CharField(write_only=True, max_length=150)
    lastName      = serializers.CharField(write_only=True, max_length=150)
    email         = serializers.EmailField(write_only=True)
    providerCode  = serializers.CharField(write_only=True, max_length=20)
    password      = serializers.CharField(write_only=True, min_length=8)

    # ---- validation ----
    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate_providerCode(self, value):
        return value.strip().upper()

    # ---- create ----
    @transaction.atomic
    def create(self, validated):
        user = User.objects.create_user(
            email=validated["email"],
            password=validated["password"],
            first_name=validated["firstName"],
            last_name=validated["lastName"],
            role=Role.INVIGILATOR,
            is_active=True,
        )
        # StaffProfile is created by the post_save signal.
        staff = StaffProfile.objects.get(user=user)
        staff.provider_code = validated["providerCode"]
        staff.save(update_fields=["provider_code"])

        # Best-effort link to a ProviderCentre row if one already exists.
        provider = ProviderCentre.objects.filter(code=validated["providerCode"]).first()
        if provider:
            InvigilatorProviderLink.objects.create(
                user=user, provider=provider, is_primary=True
            )

        # TODO (post-MVP): trigger welcome email with one-time password reset link.
        return user

    def to_representation(self, instance):
        return InvigilatorSerializer(instance, context=self.context).data


# ---------------------------------------------------------------------------
# Update Invigilator (admin edit dialog)
# ---------------------------------------------------------------------------
class UpdateInvigilatorSerializer(serializers.Serializer):
    firstName     = serializers.CharField(max_length=150, required=False)
    lastName      = serializers.CharField(max_length=150, required=False)
    email         = serializers.EmailField(required=False)
    providerCode  = serializers.CharField(max_length=20, required=False)
    isActive      = serializers.BooleanField(required=False)

    def validate_email(self, value):
        instance: User = self.instance
        qs = User.objects.filter(email__iexact=value)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Email already in use.")
        return value.lower()

    @transaction.atomic
    def update(self, instance: User, validated):
        for src, dst in (("firstName", "first_name"),
                         ("lastName", "last_name"),
                         ("email", "email"),
                         ("isActive", "is_active")):
            if src in validated:
                setattr(instance, dst, validated[src])
        instance.save()

        if "providerCode" in validated:
            sp, _ = StaffProfile.objects.get_or_create(user=instance)
            sp.provider_code = validated["providerCode"].strip().upper()
            sp.save(update_fields=["provider_code"])

        return instance

    def to_representation(self, instance):
        return InvigilatorSerializer(instance, context=self.context).data


# ---------------------------------------------------------------------------
# Availability slots
# ---------------------------------------------------------------------------
class AvailabilitySerializer(serializers.ModelSerializer):
    dayOfWeek = serializers.IntegerField(source="day_of_week")
    startTime = serializers.TimeField(source="start_time")
    endTime   = serializers.TimeField(source="end_time")
    isActive  = serializers.BooleanField(source="is_active")

    class Meta:
        model = InvigilatorAvailability
        fields = ["id", "dayOfWeek", "startTime", "endTime", "isActive"]
