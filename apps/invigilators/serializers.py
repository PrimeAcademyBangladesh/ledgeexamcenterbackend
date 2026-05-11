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
from apps.exams.models import ExamSession
from django.utils import timezone

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


class ProviderDropDownSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderCentre
        fields = ["id", "name", "code"]
        read_only_fields = ["id", "name", "code"]



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
    upcomingSessionCount = serializers.SerializerMethodField()
    total_invigitalor = serializers.SerializerMethodField()
    active_invigilator = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "firstName", "lastName", "email",
            "providerCode", "providerName",
            "isActive", "createdAt", "assignedSessionCount",
            "upcomingSessionCount", "total_invigitalor", "active_invigilator"
        ]
        read_only_fields = ["id", "createdAt", "providerName", "assignedSessionCount"]

    # ----- helpers -----
    def _primary_link(self, obj) -> InvigilatorProviderLink | None:
        return (
            obj.provider_links
            .filter(ended_at__isnull=True)
            .select_related("provider")
            .order_by("-is_primary", "provider__name")
            .first()
        )

    def get_providerCode(self, obj) -> str:
        link = self._primary_link(obj)
        return link.provider.code if link else ""

    def get_providerName(self, obj) -> str:
        link = self._primary_link(obj)
        return link.provider.name if link else ""

    def get_assignedSessionCount(self, obj) -> int:
        # Lazy import — avoids circular import with apps.exams.
        try:
            return ExamSession.objects.filter(invigilator=obj).count()
        except Exception:
            return 0
        
    def get_upcomingSessionCount(self, obj) -> int:
        try:
            now = timezone.now()
            return ExamSession.objects.filter(invigilator=obj, start_time__gt=now).count()
        except Exception:
            return 0

    def get_total_invigitalor(self, obj) -> int:
        return User.objects.filter(role=Role.INVIGILATOR).count()

    def get_active_invigilator(self, obj) -> int:
        return User.objects.filter(role=Role.INVIGILATOR, is_active=True).count()


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
        provider = ProviderCentre.objects.filter(code=validated["providerCode"]).first()
        if not provider:
            raise serializers.ValidationError(
                {"providerCode": f"No provider centre with code {validated['providerCode']}."}
            )

        user = User.objects.create_user(
            email=validated["email"],
            password=validated["password"],
            first_name=validated["firstName"],
            last_name=validated["lastName"],
            role=Role.INVIGILATOR,
            is_active=True,
        )
        # StaffProfile is created by the post_save signal; nothing extra to set.
        StaffProfile.objects.get_or_create(user=user)

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
            code = validated["providerCode"].strip().upper()
            provider = ProviderCentre.objects.filter(code=code).first()
            if not provider:
                raise serializers.ValidationError(
                    {"providerCode": f"No provider centre with code {code}."}
                )
            # Mark previous primary link inactive (if it points elsewhere) and
            # upsert the link to the requested provider.
            InvigilatorProviderLink.objects.filter(
                user=instance, is_primary=True, ended_at__isnull=True,
            ).exclude(provider=provider).update(is_primary=False)
            link, created = InvigilatorProviderLink.objects.get_or_create(
                user=instance, provider=provider,
                defaults={"is_primary": True},
            )
            if not created:
                link.is_primary = True
                link.ended_at = None
                link.save(update_fields=["is_primary", "ended_at"])

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
