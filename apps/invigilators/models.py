"""
Invigilators app — domain models.

Notes
-----
* The User account + StaffProfile are created by the `users` app.
  This app augments invigilators with operational data:
    - ProviderCentre  : the test-centre / training-provider record
    - InvigilatorProviderLink : optional explicit M2M-through if an invigilator
                                works across multiple centres (most have one)
    - InvigilatorAvailability : optional weekly availability windows
* Assigned exam sessions live in `apps.exams.ExamSession` (FK -> User).
  We expose convenience reverse accessors via `User.invigilator_sessions`.
"""

import uuid
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# ProviderCentre — the legal/operational test centre an invigilator belongs to
# ---------------------------------------------------------------------------
class ProviderCentre(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=200)
    code = models.CharField(
        max_length=20,
        unique=True,
        validators=[RegexValidator(r"^[A-Z0-9\-]{3,20}$",
                                   "Provider code must be uppercase letters/digits, e.g. PRV001")],
        help_text="Short uppercase code shown on the invigilator profile.",
    )

    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=80, blank=True)
    postcode = models.CharField(max_length=12, blank=True)
    country = models.CharField(max_length=80, blank=True, default="United Kingdom")

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Provider centre"
        verbose_name_plural = "Provider centres"
        indexes = [models.Index(fields=["code"]), models.Index(fields=["is_active"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


# ---------------------------------------------------------------------------
# Invigilator ↔ Provider link
#   For most users we set provider_code on StaffProfile.  This through-table
#   is reserved for the rare invigilator who works across multiple centres.
# ---------------------------------------------------------------------------
class InvigilatorProviderLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_links",
        limit_choices_to={"role": "invigilator"},
    )
    provider = models.ForeignKey(
        ProviderCentre,
        on_delete=models.CASCADE,
        related_name="invigilator_links",
    )
    is_primary = models.BooleanField(
        default=True,
        help_text="The invigilator's main centre. Used when only one code is shown in UI.",
    )
    started_at = models.DateField(default=timezone.now)
    ended_at = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ("user", "provider")
        ordering = ["-is_primary", "provider__name"]

    def __str__(self) -> str:
        return f"{self.user} @ {self.provider.code}"


# ---------------------------------------------------------------------------
# Optional: weekly availability windows.  Used by the future
# Admin "Assign invigilator" picker to filter only available staff.
# ---------------------------------------------------------------------------
class InvigilatorAvailability(models.Model):
    DAY_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availability_slots",
        limit_choices_to={"role": "invigilator"},
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["user", "day_of_week", "start_time"]
        verbose_name_plural = "Invigilator availability"

    def __str__(self) -> str:
        return f"{self.user} {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"
