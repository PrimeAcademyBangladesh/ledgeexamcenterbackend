"""
apps/qualifications/models.py
Lead Edge Ltd EPAO Exam Platform
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from .querysets import (
    LevelQuerySet,
    QualificationEnrollmentQuerySet,
    QualificationQuerySet,
    QualificationUnitQuerySet,
    SectorQuerySet,
)


def _unique_slug(instance, raw_value: str) -> str:
    max_length = instance._meta.get_field("slug").max_length
    base = slugify(raw_value)[:max_length] or str(uuid.uuid4())[:8]
    candidate = base
    suffix = 2
    queryset = instance.__class__.objects.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    while queryset.filter(slug=candidate).exists():
        suffix_text = f"-{suffix}"
        candidate = f"{base[:max_length - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return candidate


def validate_qualification_business_rules(
    *,
    default_pass_boundary,
    default_merit_boundary,
    default_distinction_boundary,
    min_bank_size,
    recommended_bank_size,
) -> None:
    errors = {}
    if (
        default_pass_boundary is not None
        and default_merit_boundary is not None
        and default_distinction_boundary is not None
        and not (
            default_pass_boundary
            < default_merit_boundary
            < default_distinction_boundary
        )
    ):
        errors["default_merit_boundary"] = (
            "Grade boundaries must satisfy: pass < merit < distinction."
        )
    if (
        min_bank_size is not None
        and recommended_bank_size is not None
        and min_bank_size > recommended_bank_size
    ):
        errors["min_bank_size"] = "min_bank_size cannot exceed recommended_bank_size."
    if errors:
        raise ValidationError(errors)


# ────────────────────────────────────────────────────────────
#  Sector
# ────────────────────────────────────────────────────────────
class Sector(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=16, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SectorQuerySet.as_manager()

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [
            models.Index(fields=["is_active", "sort_order"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, self.name)
        super().save(*args, **kwargs)


# ────────────────────────────────────────────────────────────
#  Level (RQF)
# ────────────────────────────────────────────────────────────

class Level(models.Model):
    STATUS_LEVEL = [
        ("", "Select a Level"),
        ("level-1", "Level 1"),
        ("level-2", "Level 2"),
        ("level-3", "Level 3"),
        ("level-4", "Level 4"),
        ("level-5", "Level 5"),
        ("level-6", "Level 6"),
        ("level-7", "Level 7"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, choices=STATUS_LEVEL, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LevelQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ────────────────────────────────────────────────────────────
#  Qualification
# ────────────────────────────────────────────────────────────
class Qualification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    code = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=200, db_index=True)
    slug = models.SlugField(unique=True, blank=True)
    sector = models.ForeignKey(
        Sector, on_delete=models.PROTECT, related_name="qualifications"
    )
    level = models.ForeignKey(
        Level, on_delete=models.PROTECT, related_name="qualifications"
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    default_questions_per_exam = models.PositiveIntegerField(default=40)
    default_time_limit_minutes = models.PositiveIntegerField(default=60)
    default_pass_boundary = models.PositiveSmallIntegerField(
        default=50, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    default_merit_boundary = models.PositiveSmallIntegerField(
        default=70, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    default_distinction_boundary = models.PositiveSmallIntegerField(
        default=85, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    min_bank_size = models.PositiveIntegerField(default=100)
    recommended_bank_size = models.PositiveIntegerField(default=200)

    resit_unseen_ratio = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    resit_fail_margin_percent = models.PositiveSmallIntegerField(default=5)
    max_resit_attempts = models.PositiveSmallIntegerField(default=2)
    resit_cooldown_days = models.PositiveSmallIntegerField(default=14)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = QualificationQuerySet.as_manager()

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["is_active", "title"]),
            models.Index(fields=["sector", "level", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(default_pass_boundary__gte=0, default_pass_boundary__lte=100)
                    & models.Q(default_merit_boundary__gte=0, default_merit_boundary__lte=100)
                    & models.Q(default_distinction_boundary__gte=0, default_distinction_boundary__lte=100)
                ),
                name="qualification_default_boundaries_0_to_100",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(default_pass_boundary__lt=models.F("default_merit_boundary"))
                    & models.Q(default_merit_boundary__lt=models.F("default_distinction_boundary"))
                ),
                name="qualification_default_boundaries_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(min_bank_size__lte=models.F("recommended_bank_size")),
                name="qualification_bank_size_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(resit_unseen_ratio__gte=Decimal("0.00"), resit_unseen_ratio__lte=Decimal("1.00")),
                name="qualification_resit_unseen_ratio_0_to_1",
            ),
            models.CheckConstraint(
                condition=models.Q(resit_fail_margin_percent__gte=0, resit_fail_margin_percent__lte=100),
                name="qualification_resit_fail_margin_0_to_100",
            ),
            models.CheckConstraint(
                condition=models.Q(default_questions_per_exam__gt=0, default_time_limit_minutes__gt=0),
                name="qualification_exam_defaults_positive",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, f"{self.code}-{self.title}")
        super().save(*args, **kwargs)

    def clean(self):
        validate_qualification_business_rules(
            default_pass_boundary=self.default_pass_boundary,
            default_merit_boundary=self.default_merit_boundary,
            default_distinction_boundary=self.default_distinction_boundary,
            min_bank_size=self.min_bank_size,
            recommended_bank_size=self.recommended_bank_size,
        )


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
class QualificationUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    qualification = models.ForeignKey(
        Qualification, on_delete=models.CASCADE, related_name="units"
    )
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    weight = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = QualificationUnitQuerySet.as_manager()

    class Meta:
        ordering = ["qualification", "sort_order"]
        indexes = [
            models.Index(fields=["qualification", "sort_order"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["qualification", "code"],
                name="unique_qualification_unit_code",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gt=0),
                name="qualification_unit_weight_positive",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.title}"


# ────────────────────────────────────────────────────────────
#  QualificationEnrollment
# ────────────────────────────────────────────────────────────
class QualificationEnrollment(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("withdrawn", "Withdrawn"),
        ("completed", "Completed"),
        ("suspended", "Suspended"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
        limit_choices_to={"role": "learner"},
    )
    qualification = models.ForeignKey(
        Qualification, on_delete=models.PROTECT, related_name="enrollments"
    )
    cohort = models.CharField(max_length=40, db_index=True)
    employer = models.CharField(max_length=200, blank=True, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active", db_index=True)

    enrolled_at = models.DateField(db_index=True)
    expected_end_date = models.DateField(null=True, blank=True)
    completed_at = models.DateField(null=True, blank=True)
    withdrawn_at = models.DateField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = QualificationEnrollmentQuerySet.as_manager()

    class Meta:
        ordering = ["-enrolled_at"]
        indexes = [
            models.Index(fields=["learner", "status"]),
            models.Index(fields=["qualification", "status"]),
            models.Index(fields=["status", "-enrolled_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "qualification", "cohort"],
                name="unique_qualification_enrollment_cohort",
            ),
        ]

    def __str__(self):
        return f"{self.learner} → {self.qualification.code} ({self.cohort})"
