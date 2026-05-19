import django.db.models.deletion
from django.db import migrations, models


def backfill_session_enrollment(apps, schema_editor):
    ExamSession = apps.get_model("exams", "ExamSession")
    Enrollment = apps.get_model("learners", "Enrollment")

    for session in ExamSession.objects.select_related("exam_config").all():
        enrollment = (
            Enrollment.objects.filter(
                learner__user_id=session.learner_id,
                qualification_id=session.exam_config.qualification_id,
                status="active",
            )
            .order_by("-enrolled_at", "-created_at")
            .first()
        )
        if enrollment is None:
            enrollment = (
                Enrollment.objects.filter(
                    learner__user_id=session.learner_id,
                    qualification_id=session.exam_config.qualification_id,
                )
                .order_by("-enrolled_at", "-created_at")
                .first()
            )
        if enrollment is not None:
            session.enrollment_id = enrollment.id
            session.save(update_fields=["enrollment"])


class Migration(migrations.Migration):

    dependencies = [
        ("learners", "0003_reasonableadjustment_reasonable_adjustment_must_be_accepted_or_denied"),
        ("exams", "0003_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="examsession",
            name="enrollment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="exam_sessions",
                to="learners.enrollment",
            ),
        ),
        migrations.AddIndex(
            model_name="examsession",
            index=models.Index(fields=["enrollment", "status"], name="exams_exams_enrollm_9b60ad_idx"),
        ),
        migrations.RunPython(backfill_session_enrollment, migrations.RunPython.noop),
    ]
