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
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Question
from .permissions import IsAdminOrStaffReadOnly
from .serializers import (
    BulkImportSerializer,
    QuestionSerializer,
)


class QuestionViewSet(viewsets.ModelViewSet):
    # Serializer only emits the FK id; no select_related needed.
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
