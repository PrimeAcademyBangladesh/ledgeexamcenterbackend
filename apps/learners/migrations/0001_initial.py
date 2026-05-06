import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("qualifications", "0002_constraints_and_slug_safety"),
    ]

    operations = [
        migrations.CreateModel(
            name="Enrollment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("cohort", models.CharField(help_text='e.g. "2026-Spring"', max_length=40)),
                ("employer", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("withdrawn", "Withdrawn"),
                            ("completed", "Completed"),
                            ("suspended", "Suspended"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=20,
                    ),
                ),
                ("enrolled_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expected_end_date", models.DateField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                ("withdrawal_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "learner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="enrollments",
                        to="users.learnerprofile",
                    ),
                ),
                (
                    "qualification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="learner_enrollments",
                        to="qualifications.qualification",
                    ),
                ),
            ],
            options={
                "db_table": "enrollments",
                "ordering": ["-enrolled_at"],
                "indexes": [
                    models.Index(fields=["learner", "status"], name="enrollment_learner_status_idx"),
                    models.Index(fields=["qualification", "status"], name="enrollment_qualification_status_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("learner", "qualification", "cohort"),
                        name="unique_learner_enrollment_cohort",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ReasonableAdjustment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("notes", models.TextField(help_text="What the learner needs (extra time, reader, etc.)")),
                ("accepted", models.BooleanField(default=False)),
                ("denied", models.BooleanField(default=False)),
                ("denial_reason", models.TextField(blank=True)),
                ("extra_time_minutes", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_adjustments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "learner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reasonable_adjustments",
                        to="users.learnerprofile",
                    ),
                ),
            ],
            options={
                "db_table": "reasonable_adjustments",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["learner", "accepted"], name="reasonable_learner_accepted_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(accepted=False) | models.Q(denied=False),
                        name="reasonable_adjustment_not_accepted_and_denied",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(denied=False) | ~models.Q(denial_reason=""),
                        name="reasonable_adjustment_denial_has_reason",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(extra_time_minutes__lte=240),
                        name="reasonable_adjustment_extra_time_lte_240",
                    ),
                ],
            },
        ),
    ]
