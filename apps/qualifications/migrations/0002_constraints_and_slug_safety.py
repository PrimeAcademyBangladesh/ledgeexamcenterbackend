from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qualifications", "0001_initial"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="qualificationenrollment",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="qualificationunit",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="level",
            constraint=models.CheckConstraint(
                condition=models.Q(numeric_value__gte=1, numeric_value__lte=8),
                name="level_numeric_value_between_1_and_8",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualification",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(default_pass_boundary__gte=0, default_pass_boundary__lte=100)
                    & models.Q(default_merit_boundary__gte=0, default_merit_boundary__lte=100)
                    & models.Q(default_distinction_boundary__gte=0, default_distinction_boundary__lte=100)
                ),
                name="qualification_default_boundaries_0_to_100",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualification",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(default_pass_boundary__lt=models.F("default_merit_boundary"))
                    & models.Q(default_merit_boundary__lt=models.F("default_distinction_boundary"))
                ),
                name="qualification_default_boundaries_ordered",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualification",
            constraint=models.CheckConstraint(
                condition=models.Q(min_bank_size__lte=models.F("recommended_bank_size")),
                name="qualification_bank_size_ordered",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualification",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    resit_unseen_ratio__gte=Decimal("0.00"),
                    resit_unseen_ratio__lte=Decimal("1.00"),
                ),
                name="qualification_resit_unseen_ratio_0_to_1",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualification",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    resit_fail_margin_percent__gte=0,
                    resit_fail_margin_percent__lte=100,
                ),
                name="qualification_resit_fail_margin_0_to_100",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualification",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    default_questions_per_exam__gt=0,
                    default_time_limit_minutes__gt=0,
                ),
                name="qualification_exam_defaults_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualificationenrollment",
            constraint=models.UniqueConstraint(
                fields=("learner", "qualification", "cohort"),
                name="unique_qualification_enrollment_cohort",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualificationunit",
            constraint=models.UniqueConstraint(
                fields=("qualification", "code"),
                name="unique_qualification_unit_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="qualificationunit",
            constraint=models.CheckConstraint(
                condition=models.Q(weight__gt=0),
                name="qualification_unit_weight_positive",
            ),
        ),
    ]
