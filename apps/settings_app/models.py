from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SystemSettings(models.Model):
    """Singleton row for platform-wide defaults."""

    org_name = models.CharField(max_length=200, default="Lead Edge Ltd")
    org_website = models.URLField(default="https://leadedgeltd.org/")
    support_email = models.EmailField(default="support@leadedgeltd.org")
    logo_url = models.ImageField(upload_to="settings/logo/", blank=True, null=True)

    default_pass_boundary = models.PositiveSmallIntegerField(
        default=60, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    default_merit_boundary = models.PositiveSmallIntegerField(
        default=70, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    default_distinction_boundary = models.PositiveSmallIntegerField(
        default=85, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    default_time_limit_minutes = models.PositiveIntegerField(
        default=60, validators=[MinValueValidator(1)]
    )
    default_questions_per_exam = models.PositiveIntegerField(
        default=40, validators=[MinValueValidator(1)]
    )
    default_shuffle_questions = models.BooleanField(default=True)
    default_shuffle_options = models.BooleanField(default=True)
    default_strict_mode = models.BooleanField(default=True)

    pin_format = models.CharField(max_length=20, default="6 digits")
    pin_expiry_minutes_before = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1)]
    )
    max_violations_before_auto_submit = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )

    allow_mock_tests = models.BooleanField(default=True)
    show_explanations_on_mock = models.BooleanField(default=True)
    show_explanations_on_live = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="settings_updates",
    )

    class Meta:
        db_table = "system_settings"
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    def __str__(self):
        return "System Settings"

    def clean(self):
        if not (
            self.default_pass_boundary
            < self.default_merit_boundary
            < self.default_distinction_boundary
        ):
            raise ValidationError(
                "Grade boundaries must be ordered: Pass < Merit < Distinction."
            )

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SettingsAuditLog(models.Model):
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="settings_audit_logs",
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    field = models.CharField(max_length=80)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)

    class Meta:
        db_table = "settings_audit_logs"
        ordering = ["-changed_at"]
        verbose_name = "Settings Audit Log"
        verbose_name_plural = "Settings Audit Logs"

    def __str__(self):
        return f"{self.field} @ {self.changed_at:%Y-%m-%d %H:%M:%S}"
