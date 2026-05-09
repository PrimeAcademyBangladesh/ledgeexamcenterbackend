"""
Lead Edge Ltd — Questions serializers
=====================================
Two serializer classes:

1. QuestionSerializer — Admin (full payload incl. correct_answers, explanation).
   Used by AdminQuestionBank.tsx.

2. ExamQuestionSerializer — Learner-safe (no correct_answers, no explanation).
   Used by exam/serializers.ValidatePinResponseSerializer when delivering the
   frozen paper. Mirrors src/services/api/types.ts ExamQuestion.

3. BulkImportSerializer — for POST /api/questions/bulk-import/.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiExample, extend_schema_serializer
from rest_framework import serializers

from .models import Question


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Question Create",
            value={
                "qualification": "11111111-1111-1111-1111-111111111111",
                "question_text": "What does EPAO stand for?",
                "question_type": "single",
                "options": [
                    "End Point Assessment Organisation",
                    "Education Provider Award Office",
                    "External Performance Audit Office",
                ],
                "correct_answers": [0],
                "explanation": "EPAO stands for End Point Assessment Organisation.",
                "tags": ["epa", "terminology"],
            },
            request_only=True,
        ),
    ]
)
class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = [
            "id",
            "qualification",          # UUID; UI sends qualificationId
            "question_text",
            "question_type",
            "options",
            "correct_answers",
            "explanation",
            "tags",
            "image_qs",
            "is_active",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "created_by"]
        extra_kwargs = {
            "qualification": {"required": True},
            "image_qs": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        # Run model-level invariants without persisting. For partial updates,
        # merge incoming values onto the existing instance so image-only PATCH
        # requests do not fail due to unrelated required fields missing.
        payload = {}
        if self.instance is not None:
            payload = {
                "question_text": self.instance.question_text,
                "question_type": self.instance.question_type,
                "options": self.instance.options,
                "correct_answers": self.instance.correct_answers,
                "explanation": self.instance.explanation,
                "tags": self.instance.tags,
                "image_qs": self.instance.image_qs,
                "is_active": self.instance.is_active,
                "created_by": self.instance.created_by,
            }
        payload.update({k: v for k, v in attrs.items() if k != "qualification"})
        instance = Question(**payload)
        try:
            instance.validate_payload()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class ExamQuestionSerializer(serializers.ModelSerializer):
    """Stripped payload sent to the learner during an active exam."""

    class Meta:
        model = Question
        fields = [
            "id",
            "question_text",
            "question_type",
            "options",
            "image_qs",
        ]
        read_only_fields = fields


class BulkImportItemSerializer(serializers.Serializer):
    question_text = serializers.CharField()
    question_type = serializers.ChoiceField(choices=["single", "multiple"], default="single")
    options = serializers.ListField(child=serializers.CharField(), min_length=2)
    correct_answers = serializers.ListField(child=serializers.IntegerField(min_value=0))
    explanation = serializers.CharField(required=False, allow_blank=True, default="")
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class BulkImportSerializer(serializers.Serializer):
    qualification_id = serializers.UUIDField()
    questions = BulkImportItemSerializer(many=True)


class BulkImportResultSerializer(serializers.Serializer):
    imported = serializers.IntegerField()
    ids = serializers.ListField(child=serializers.UUIDField())
