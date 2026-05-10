"""
Lead Edge Ltd — Questions app models
====================================
Backs the AdminQuestionBank UI and feeds the exam paper-freezing flow
(see exam/services.select_questions_for_learner).

Naming: snake_case in DB; the React app uses camelCase via the Axios
interceptor in src/services/api/client.ts.

Key invariants:
- A Question always belongs to ONE Qualification (qualificationId in UI).
- options is a JSONField list[str]; correct_answers is a JSONField list[int]
  (zero-based indexes into options).
- question_type = 'single' | 'multiple' (mirrors UI QuestionType).
- is_active=False is a soft-delete; the bank-health counter excludes inactives.
- Tags are free-text labels stored as JSONField list[str].
"""

import uuid
from django.conf import settings
from django.db import models


class Question(models.Model):
    QUESTION_TYPE_CHOICES = [
        ("single", "Single answer"),
        ("multiple", "Multiple answer"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    qualification = models.ForeignKey(
        "qualifications.Qualification",
        on_delete=models.CASCADE,
        related_name="questions",
    )
    question_text = models.TextField()
    question_type = models.CharField(
        max_length=10, choices=QUESTION_TYPE_CHOICES, default="single"
    )
    options = models.JSONField(default=list)
    correct_answers = models.JSONField(default=list)
    explanation = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    image_qs = models.ImageField(upload_to="questions_images/", blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_questions",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["qualification", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.qualification_id} – {self.question_text[:60]}"

    # -----------------------------------------------------------------
    # Validation helpers — call from serializer.validate(), not save(),
    # so DRF returns field-level 400s instead of 500s.
    # -----------------------------------------------------------------
    def validate_payload(self) -> None:
        from django.core.exceptions import ValidationError
        if not isinstance(self.options, list) or len(self.options) < 2:
            raise ValidationError({"options": "At least 2 options required."})
        if any(not isinstance(o, str) or not o.strip() for o in self.options):
            raise ValidationError({"options": "All options must be non-empty strings."})
        if not isinstance(self.correct_answers, list) or not self.correct_answers:
            raise ValidationError({"correct_answers": "At least one correct answer required."})
        max_idx = len(self.options) - 1
        if any((not isinstance(i, int)) or i < 0 or i > max_idx for i in self.correct_answers):
            raise ValidationError({"correct_answers": "Indexes out of range."})
        if self.question_type == "single" and len(self.correct_answers) != 1:
            raise ValidationError({"correct_answers": "Single-answer questions need exactly one index."})
