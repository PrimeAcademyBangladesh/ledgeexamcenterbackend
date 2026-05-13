from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SettingsAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("field", models.CharField(max_length=80)),
                ("old_value", models.TextField(blank=True)),
                ("new_value", models.TextField(blank=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="settings_audit_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Settings Audit Log",
                "verbose_name_plural": "Settings Audit Logs",
                "db_table": "settings_audit_logs",
                "ordering": ["-changed_at"],
            },
        ),
        migrations.CreateModel(
            name="SystemSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("org_name", models.CharField(default="Lead Edge Ltd", max_length=200)),
                ("org_website", models.URLField(default="https://leadedgeltd.org/")),
                ("support_email", models.EmailField(default="support@leadedgeltd.org", max_length=254)),
                ("logo_url", models.ImageField(blank=True, null=True, upload_to="settings/logo/")),
                ("default_pass_boundary", models.PositiveSmallIntegerField(default=60, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("default_merit_boundary", models.PositiveSmallIntegerField(default=70, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("default_distinction_boundary", models.PositiveSmallIntegerField(default=85, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("default_time_limit_minutes", models.PositiveIntegerField(default=60, validators=[django.core.validators.MinValueValidator(1)])),
                ("default_questions_per_exam", models.PositiveIntegerField(default=40, validators=[django.core.validators.MinValueValidator(1)])),
                ("default_shuffle_questions", models.BooleanField(default=True)),
                ("default_shuffle_options", models.BooleanField(default=True)),
                ("default_strict_mode", models.BooleanField(default=True)),
                ("pin_format", models.CharField(default="6 digits", max_length=20)),
                ("pin_expiry_minutes_before", models.PositiveSmallIntegerField(default=5, validators=[django.core.validators.MinValueValidator(1)])),
                ("max_violations_before_auto_submit", models.PositiveSmallIntegerField(default=3, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10)])),
                ("allow_mock_tests", models.BooleanField(default=True)),
                ("show_explanations_on_mock", models.BooleanField(default=True)),
                ("show_explanations_on_live", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="settings_updates", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "System Settings",
                "verbose_name_plural": "System Settings",
                "db_table": "system_settings",
            },
        ),
    ]
