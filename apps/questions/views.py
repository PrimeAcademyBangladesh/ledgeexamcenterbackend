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

Frontend touchpoints:
- AdminQuestionBank.tsx -> questionService.listQuestions / createQuestion / deleteQuestion.
- exam/services.select_questions_for_learner reads Question.objects directly,
  it does not go through this API.
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view, inline_serializer
from rest_framework import filters, serializers as drf_serializers, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.schemas import DEFAULT_ERROR_RESPONSES, envelope_detail

from .models import Question
from .permissions import IsAdminOrStaffReadOnly
from .serializers import QuestionSerializer


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
        parameters=[
            QUESTION_QUALIFICATION_PARAM,
            OpenApiParameter(name="qualification", exclude=True),
        ],
        responses={
            200: inline_serializer(
                name="QuestionListEnvelope",
                fields={
                    "success": drf_serializers.BooleanField(default=True),
                    "message": drf_serializers.CharField(),
                    "data": inline_serializer(
                        name="QuestionListData",
                        fields={
                            "count": drf_serializers.IntegerField(),
                            "next": drf_serializers.URLField(allow_null=True, required=False),
                            "previous": drf_serializers.URLField(allow_null=True, required=False),
                            "results": QuestionSerializer(many=True),
                            "pool_total": drf_serializers.IntegerField(help_text="Total questions matching current filters."),
                            "pool_active": drf_serializers.IntegerField(help_text="Active questions matching current filters."),
                        },
                    ),
                },
            ),
            **DEFAULT_ERROR_RESPONSES,
        },
    ),
    retrieve=extend_schema(
        tags=["Question"],
        summary="Retrieve a question",
        responses={200: envelope_detail(QuestionSerializer, message_example="Question retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=["Question"],
        summary="Create a question",
        request={"multipart/form-data": QuestionSerializer, "application/json": QuestionSerializer},
        responses={201: envelope_detail(QuestionSerializer, message_example="Question created successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    update=extend_schema(
        tags=["Question"],
        summary="Replace a question",
        request={"multipart/form-data": QuestionSerializer, "application/json": QuestionSerializer},
        responses={200: envelope_detail(QuestionSerializer, message_example="Question updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        tags=["Question"],
        summary="Partially update a question",
        request={"multipart/form-data": QuestionSerializer, "application/json": QuestionSerializer},
        responses={200: envelope_detail(QuestionSerializer, message_example="Question updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    destroy=extend_schema(
        tags=["Question"],
        summary="Soft-delete a question",
        description="Marks `is_active=false` so historical sessions and seen-question records remain valid.",
        responses={204: None, **DEFAULT_ERROR_RESPONSES},
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
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    permission_classes = [IsAdminOrStaffReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active", "question_type"]
    search_fields = ["question_text", "tags"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        qualification_id = self.request.query_params.get("qualification_id")
        if qualification_id:
            qs = qs.filter(qualification_id=qualification_id)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        pool_total = qs.count()
        pool_active = qs.filter(is_active=True).count()

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data["pool_total"] = pool_total
            response.data["pool_active"] = pool_active
            return response

        serializer = self.get_serializer(qs, many=True)
        return Response({
            "results": serializer.data,
            "pool_total": pool_total,
            "pool_active": pool_active,
        })

    def destroy(self, request, *args, **kwargs):
        """Soft-delete: keeps historical exam papers and seen-question records intact."""
        obj = self.get_object()
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
