import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    INVIGILATOR = "invigilator", "Invigilator"
    LEARNER = "learner", "Learner"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        if extra.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=80, db_index=True)
    last_name = models.CharField(max_length=80, db_index=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.LEARNER)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now, db_index=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        db_table = "users"
        indexes = [models.Index(fields=["role"])]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email).lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.email} ({self.role})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


# ── ID Generators ────────────────────────────────────────────

uln_validator = RegexValidator(r"^\d{10}$", "ULN must be exactly 10 digits.")


def generate_learner_id() -> str:
    """LE-YY-XXXXXX, sequential per year."""
    year = timezone.now().strftime("%y")
    prefix = f"LE-{year}-"
    last = LearnerProfile.objects.filter(learner_id__startswith=prefix).order_by("-learner_id").first()
    next_num = (int(last.learner_id.split("-")[-1]) + 1) if last else 1
    return f"{prefix}{next_num:06d}"


def generate_staff_id(role: str) -> str:
    """ADM-YY-XXXX or INV-YY-XXXX."""
    code = {Role.ADMIN: "ADM", Role.INVIGILATOR: "INV"}[role]
    year = timezone.now().strftime("%y")
    prefix = f"{code}-{year}-"
    last = StaffProfile.objects.filter(staff_id__startswith=prefix).order_by("-staff_id").first()
    next_num = (int(last.staff_id.split("-")[-1]) + 1) if last else 1
    return f"{prefix}{next_num:04d}"


# ── Learner Profile ──────────────────────────────────────────

class LearnerProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="learner_profile",
        limit_choices_to={"role": Role.LEARNER},
    )
    learner_id = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    # ULN is issued externally by the UK LRS (ESFA). Optional — many learners
    # arrive without one. `null=True` is essential: with `unique=True`, multiple
    # rows would collide on empty strings; multiple NULLs are allowed.
    uln = models.CharField(
        max_length=10, unique=True, null=True, blank=True,
        validators=[uln_validator], db_index=True,
    )

    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    photo = models.ImageField(upload_to="learners/photos/", null=True, blank=True)
    id_document = models.FileField(upload_to="learners/id_docs/", null=True, blank=True)
    id_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "learner_profiles"

    def save(self, *args, **kwargs):
        if not self.learner_id:
            self.learner_id = generate_learner_id()
        # ULN is left as-is. If blank, store NULL so the unique index permits
        # multiple ULN-less learners.
        if not self.uln:
            self.uln = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.learner_id} — {self.user.full_name}"


# ── Staff Profile ────────────────────────────────────────────

class StaffProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="staff_profile",
        limit_choices_to={"role__in": [Role.ADMIN, Role.INVIGILATOR]},
    )
    staff_id = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    job_title = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    photo = models.ImageField(upload_to="staff/photos/", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff_profiles"

    def save(self, *args, **kwargs):
        if not self.staff_id:
            self.staff_id = generate_staff_id(self.user.role)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff_id} — {self.user.full_name} ({self.user.role})"
