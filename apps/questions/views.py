"""
Lead Edge Ltd — Questions views
===============================
Endpoints (all under /api/):

  GET    /api/questions/?qualification_id=<uuid>&search=<str>&is_active=<bool>
  POST   /api/questions/
  GET    /api/questions/<id>/
  PUT    /api/questions/<id>/
  PATCH  /api/questions/<id>/
  DELETE /api/questions/<id>/                     (soft delete -> is_active=False)
  POST   /api/questions/bulk-import/

Frontend touchpoints:
- AdminQuestionBank.tsx -> questionService.listQuestions / createQuestion /
  deleteQuestion / (bulk import is wired client-side; switch to the bulk
  endpoint when going live).
- exam/services.select_questions_for_learner reads Question.objects directly,
  it does not go through this API.
"""

from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.schemas import DEFAULT_ERROR_RESPONSES, envelope_detail, envelope_list

from .models import Question
from .permissions import IsAdminOrStaffReadOnly
from .serializers import (
    BulkImportSerializer,
    BulkImportResultSerializer,
    QuestionSerializer,
)


QUESTION_QUALIFICATION_PARAM = OpenApiParameter(
    name="qualification_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Filter questions by qualification UUID. Kept for frontend compatibility.",
)


@extend_schema_view(
    list=extend_schema(
        tags=["Question"],
        summary="List questions",
        parameters=[QUESTION_QUALIFICATION_PARAM],
        responses={200: envelope_list(QuestionSerializer, message_example="Questions retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=["Question"],
        summary="Retrieve a question",
        responses={200: envelope_detail(QuestionSerializer, message_example="Question retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=["Question"],
        summary="Create a question",
        request=QuestionSerializer,
        responses={201: envelope_detail(QuestionSerializer, message_example="Question created successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    update=extend_schema(
        tags=["Question"],
        summary="Replace a question",
        request=QuestionSerializer,
        responses={200: envelope_detail(QuestionSerializer, message_example="Question updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        tags=["Question"],
        summary="Partially update a question",
        request=QuestionSerializer,
        responses={200: envelope_detail(QuestionSerializer, message_example="Question updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    destroy=extend_schema(
        tags=["Question"],
        summary="Soft-delete a question",
        description="Marks `is_active=false` so historical sessions and seen-question records remain valid.",
        responses={204: None, **DEFAULT_ERROR_RESPONSES},
    ),
    bulk_import=extend_schema(
        tags=["Question"],
        summary="Bulk-import questions",
        description=(
            "Create many questions for a single qualification in one request. "
            "The frontend can use this for CSV/JSON-assisted imports to avoid "
            "N sequential create calls."
        ),
        request=BulkImportSerializer,
        responses={
            201: envelope_detail(BulkImportResultSerializer, message_example="Questions imported successfully."),
            **DEFAULT_ERROR_RESPONSES,
        },
    ),
)
class QuestionViewSet(viewsets.ModelViewSet):
    """
    Admin question-bank CRUD endpoint.

    Frontend usage:
      - `GET /api/questions/` drives the Admin Question Bank table and supports
        the legacy `qualification_id` filter used by the current UI service.
      - `POST/PATCH/PUT /api/questions/` use the same serializer shape for both
        request and response.
      - `DELETE /api/questions/{id}/` is a soft delete, so the frontend should
        treat removal as archival rather than hard erasure.
      - Learner exam flows do not consume this API directly; they use the
        frozen session payload from the exams app instead.
    """
    # Serializer only emits FK/user primary keys; no select_related needed.
    queryset = Question.objects.all()
    serializer_class = QuestionSerializer
    permission_classes = [IsAdminOrStaffReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["qualification", "is_active", "question_type"]
    search_fields = ["question_text", "tags"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        # UI sends ?qualification_id=… — translate to the FK column.
        qualification_id = self.request.query_params.get("qualification_id")
        if qualification_id:
            qs = qs.filter(qualification_id=qualification_id)
        return qs

    def destroy(self, request, *args, **kwargs):
        """Soft-delete: keeps historical exam papers and seen-question records intact."""
        obj = self.get_object()
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -----------------------------------------------------------------
    # POST /api/questions/bulk-import/
    # -----------------------------------------------------------------
    @action(detail=False, methods=["post"], url_path="bulk-import")
    def bulk_import(self, request):
        ser = BulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        qualification_id = ser.validated_data["qualification_id"]
        items = ser.validated_data["questions"]
        # Permission class guarantees auth.
        creator = request.user

        # One INSERT for the whole batch instead of N.
        objs = [
            Question(qualification_id=qualification_id, created_by=creator, **item)
            for item in items
        ]
        with transaction.atomic():
            created = Question.objects.bulk_create(objs)

        return Response(
            {"imported": len(created), "ids": [str(q.id) for q in created]},
            status=status.HTTP_201_CREATED,
        )
