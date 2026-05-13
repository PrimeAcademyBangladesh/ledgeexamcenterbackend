from rest_framework import serializers

from .models import SettingsAuditLog, SystemSettings


class SettingsAuditLogSerializer(serializers.ModelSerializer):
    changedBy = serializers.SerializerMethodField()
    changedAt = serializers.DateTimeField(source="changed_at", read_only=True)
    oldValue = serializers.CharField(source="old_value", read_only=True)
    newValue = serializers.CharField(source="new_value", read_only=True)

    class Meta:
        model = SettingsAuditLog
        fields = ["field", "oldValue", "newValue", "changedAt", "changedBy"]

    def get_changedBy(self, obj) -> str:
        if not obj.changed_by:
            return ""
        return obj.changed_by.full_name or obj.changed_by.email


class SystemSettingsSerializer(serializers.ModelSerializer):
    orgName = serializers.CharField(source="org_name")
    orgWebsite = serializers.URLField(source="org_website")
    supportEmail = serializers.EmailField(source="support_email")
    logoUrl = serializers.SerializerMethodField(read_only=True)
    logo = serializers.ImageField(source="logo_url", write_only=True, required=False, allow_null=True)

    defaultPassBoundary = serializers.IntegerField(source="default_pass_boundary")
    defaultMeritBoundary = serializers.IntegerField(source="default_merit_boundary")
    defaultDistinctionBoundary = serializers.IntegerField(source="default_distinction_boundary")
    defaultTimeLimitMinutes = serializers.IntegerField(source="default_time_limit_minutes")
    defaultQuestionsPerExam = serializers.IntegerField(source="default_questions_per_exam")
    defaultShuffleQuestions = serializers.BooleanField(source="default_shuffle_questions")
    defaultShuffleOptions = serializers.BooleanField(source="default_shuffle_options")
    defaultStrictMode = serializers.BooleanField(source="default_strict_mode")

    pinFormat = serializers.CharField(source="pin_format", read_only=True)
    pinExpiryMinutesBefore = serializers.IntegerField(source="pin_expiry_minutes_before")
    maxViolationsBeforeAutoSubmit = serializers.IntegerField(source="max_violations_before_auto_submit")

    allowMockTests = serializers.BooleanField(source="allow_mock_tests")
    showExplanationsOnMock = serializers.BooleanField(source="show_explanations_on_mock")
    showExplanationsOnLive = serializers.BooleanField(source="show_explanations_on_live")
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = SystemSettings
        fields = [
            "orgName",
            "orgWebsite",
            "supportEmail",
            "logoUrl",
            "logo",
            "defaultPassBoundary",
            "defaultMeritBoundary",
            "defaultDistinctionBoundary",
            "defaultTimeLimitMinutes",
            "defaultQuestionsPerExam",
            "defaultShuffleQuestions",
            "defaultShuffleOptions",
            "defaultStrictMode",
            "pinFormat",
            "pinExpiryMinutesBefore",
            "maxViolationsBeforeAutoSubmit",
            "allowMockTests",
            "showExplanationsOnMock",
            "showExplanationsOnLive",
            "updatedAt",
        ]

    def get_logoUrl(self, obj) -> str | None:
        if not obj.logo_url:
            return None
        request = self.context.get("request")
        url = obj.logo_url.url
        return request.build_absolute_uri(url) if request else url

    def validate_logo(self, value):
        if not value:
            return value
        max_size = 2 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError("Logo must be under 2MB.")
        content_type = getattr(value, "content_type", "")
        if content_type and content_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise serializers.ValidationError("Logo must be PNG, JPG, or WEBP.")
        return value

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        pass_boundary = attrs.get(
            "default_pass_boundary",
            getattr(instance, "default_pass_boundary", None),
        )
        merit_boundary = attrs.get(
            "default_merit_boundary",
            getattr(instance, "default_merit_boundary", None),
        )
        distinction_boundary = attrs.get(
            "default_distinction_boundary",
            getattr(instance, "default_distinction_boundary", None),
        )

        if not (pass_boundary < merit_boundary < distinction_boundary):
            raise serializers.ValidationError(
                {
                    "defaultMeritBoundary": (
                        "Grade boundaries must be ordered: Pass < Merit < Distinction."
                    )
                }
            )
        return attrs

    def update(self, instance, validated_data):
        actor = self.context.get("request").user if self.context.get("request") else None
        changed = []
        for field, new_value in validated_data.items():
            old_value = getattr(instance, field)
            if old_value != new_value:
                changed.append((field, old_value, new_value))
                setattr(instance, field, new_value)

        if changed:
            instance.updated_by = actor
            instance.save()
            SettingsAuditLog.objects.bulk_create(
                [
                    SettingsAuditLog(
                        changed_by=actor,
                        field=field,
                        old_value="" if old is None else str(old),
                        new_value="" if new is None else str(new),
                    )
                    for field, old, new in changed
                ]
            )
        return instance
