"""
One-off fix for the PIN-window timezone bug.

_compute_pin_window() used to force-tag scheduled_date/scheduled_time as UTC
instead of localising them to TIME_ZONE (Europe/London). During BST
(late Mar – late Oct, UTC+1) this shifted every scheduled session's
pin_window_start/end an hour later than intended, blocking learners from
entering on time. See apps/exams/services.py::_compute_pin_window.

This command recomputes the window for every still-scheduled session using
the corrected logic, so existing bookings made before the fix don't keep
failing on exam day. Sessions that are in_progress/completed/cancelled, or
already flagged allow_immediate_start (their window is anchored to "now" at
activation time, not to scheduled_date/time), are left untouched.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.exams.models import ExamSession
from apps.exams.services import _compute_pin_window


class Command(BaseCommand):
    help = (
        "Recompute pin_window_start/end for scheduled sessions affected by the "
        "PIN-window timezone bug (run once after deploying the fix)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the recomputed windows. Without this flag, only a preview is printed.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        sessions = (
            ExamSession.objects
            .filter(status="scheduled", allow_immediate_start=False)
            .select_related("exam_config")
            .order_by("scheduled_date", "scheduled_time")
        )

        to_update = []
        for session in sessions:
            new_start, new_end = _compute_pin_window(
                session.scheduled_date, session.scheduled_time, session.exam_config,
                extra_minutes=session.extra_time_minutes or 0,
                allow_immediate_start=False,
            )
            if new_start == session.pin_window_start and new_end == session.pin_window_end:
                continue

            self.stdout.write(
                f"Session {session.id} ({session.scheduled_date} {session.scheduled_time}): "
                f"[{session.pin_window_start} → {session.pin_window_end}]  "
                f"=>  [{new_start} → {new_end}]"
            )
            session.pin_window_start = new_start
            session.pin_window_end = new_end
            to_update.append(session)

        if apply_changes and to_update:
            with transaction.atomic():
                ExamSession.objects.bulk_update(to_update, ["pin_window_start", "pin_window_end"])

        if not to_update:
            self.stdout.write(self.style.SUCCESS("No sessions needed recomputation."))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Updated {len(to_update)} session(s)."))
        else:
            self.stdout.write(self.style.WARNING(
                f"{len(to_update)} session(s) would change. Re-run with --apply to persist."
            ))
