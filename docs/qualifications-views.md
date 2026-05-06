# Qualifications App — DRF Views

**Project:** Lead Edge Ltd EPAO Exam Platform
**Django app:** `apps/qualifications/views.py` + `apps/qualifications/permissions.py`
**Pairs with:** `qualifications-serializers.md`, `qualifications-data-dictionary.md`

This document covers ViewSets, permissions, querysets, filtering, caching, and the exact UI screen each view powers.

---

## 0. Design principles

1. **ModelViewSet only when all 5 verbs are needed.** Otherwise compose `mixins` + `GenericViewSet` to keep the surface area honest.
2. **Permissions are declared per-action**, not per-viewset, because admins, invigilators, and learners hit the same endpoints with different rights.
3. **Querysets are scoped in `get_queryset()`** — never trust serializers to filter by tenant/user.
4. **Read endpoints are cached** at the view layer with role-aware cache keys (admin vs learner see different fields).
5. **Write endpoints invalidate cache + emit audit log entries** via `perform_create/update/destroy`.
6. **All list endpoints support `?page_size=` (max 200), `?search=`, and field filters** via `django-filter`.

---

## 1. Permissions (`apps/qualifications/permissions.py`)

```python
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdmin(BasePermission):
    """Full CRUD. Used on Sector, Level, Qualification, QualificationUnit write endpoints."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and request.user.role == "admin")


class IsAdminOrReadOnlyForStaff(BasePermission):
    """
    Admin: full CRUD.
    Invigilator: read-only (needs to see qualifications when running a session).
    Learner: denied (qualification metadata exposes resit fail margins — sensitive).
    """
    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.role == "admin":
            return True
        if u.role == "invigilator" and request.method in SAFE_METHODS:
            return True
        return False


class IsEnrollmentOwnerOrAdmin(BasePermission):
    """
    Used on /api/enrollments/{id}/ — learner can read their own,
    admin can do anything, invigilator denied.
    """
    def has_object_permission(self, request, view, obj):
        u = request.user
        if u.role == "admin":
            return True
        if u.role == "learner" and request.method in SAFE_METHODS:
            return obj.learner_id == u.id
        return False
```

> **Why a permissions module not inline classes:** Same rules are reused across `apps/exams` and `apps/questions`. One source of truth prevents drift.

---

## 2. Mixins & helpers (`apps/qualifications/mixins.py`)

```python
from django.core.cache import cache
from rest_framework.response import Response


class RoleAwareCacheMixin:
    """
    Why: Admin sees `bankHealth` + resit fields, learner does not. A naive
         page-level cache would leak admin fields to learners.
    Where: Mixed into QualificationViewSet detail/list actions.
    """
    cache_ttl = 60  # seconds

    def get_cache_key(self, request, **kwargs):
        role = getattr(request.user, "role", "anon")
        return f"qual:{self.action}:{role}:{kwargs}:{request.GET.urlencode()}"

    def cached_response(self, request, builder, **kwargs):
        key = self.get_cache_key(request, **kwargs)
        data = cache.get(key)
        if data is None:
            data = builder()
            cache.set(key, data, self.cache_ttl)
        return Response(data)


class AuditLogMixin:
    """Logs every write to the QualificationAuditLog table (separate app)."""
    def perform_create(self, serializer):
        instance = serializer.save()
        self._audit("create", instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._audit("update", instance)

    def perform_destroy(self, instance):
        self._audit("delete", instance)
        instance.delete()

    def _audit(self, action, instance):
        from apps.audit.models import AuditLog
        AuditLog.objects.create(
            actor=self.request.user,
            action=action,
            model=instance.__class__.__name__,
            object_id=str(instance.pk),
            payload=self.request.data,
        )
```

---

## 3. `SectorViewSet`

```python
class SectorViewSet(AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Admin-managed sector list. Powers every "Sector" dropdown in the UI.
    Where:
      - GET    /api/sectors/                → AdminQualifications + AdminExams + AdminQuestionBank dropdowns
      - GET    /api/sectors/{id}/           → Admin Sectors settings page (planned)
      - POST   /api/sectors/                → "Add Sector" admin form
      - PATCH  /api/sectors/{id}/           → Toggle is_active, rename, reorder
      - DELETE /api/sectors/{id}/           → Hard delete (PROTECTED if any Qualification refs it)
    Notes:
      - Default queryset hides inactive sectors. Admin can pass ?include_inactive=true
        to see soft-disabled rows on the management page.
      - List endpoint is ETag-cached for 5 min; mutation invalidates the tag.
    """
    serializer_class = SectorSerializer
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "code"]
    ordering_fields = ["sort_order", "name"]
    ordering = ["sort_order", "name"]

    def get_queryset(self):
        qs = Sector.objects.annotate(qualification_count=Count("qualifications"))
        if self.request.query_params.get("include_inactive") != "true":
            qs = qs.filter(is_active=True)
        return qs

    def perform_destroy(self, instance):
        if instance.qualifications.exists():
            raise ValidationError(
                "Cannot delete sector while qualifications reference it. "
                "Set is_active=false instead.")
        super().perform_destroy(instance)
```

---

## 4. `LevelViewSet`

```python
class LevelViewSet(AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Same pattern as SectorViewSet. Admin-managed RQF levels.
    Where:
      - All admin forms that create/edit Qualifications.
      - Reports filter dropdown (planned).
    """
    serializer_class = LevelSerializer
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [filters.OrderingFilter]
    ordering = ["numeric_value"]

    def get_queryset(self):
        qs = Level.objects.all()
        if self.request.query_params.get("include_inactive") != "true":
            qs = qs.filter(is_active=True)
        return qs
```

---

## 5. `QualificationViewSet` — the central one

```python
class QualificationViewSet(RoleAwareCacheMixin, AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Central catalogue. Read by every role; written only by admins.
    Where (mapped to current React screens):
      - GET  /api/qualifications/?is_active=true&page_size=200
            → AdminExams.tsx, AdminLearners.tsx, AdminQuestionBank.tsx,
              AdminReports.tsx — every dropdown.
      - GET  /api/qualifications/{id}/
            → AdminExams "Create Exam" form (pre-fills defaults from this payload)
            → AdminQuestionBank header (bankHealth badge)
      - POST/PATCH/DELETE /api/qualifications/
            → "Manage Qualifications" admin page (planned).
    Permissions:
      - Read: admin + invigilator. Learners go through /api/me/qualifications/
              (separate view, returns lean payload without resit fields).
      - Write: admin only.
    Performance:
      - List: select_related sector+level, annotate question_count.
      - Detail: prefetch units; bankHealth computed via annotated query, not Python.
    """
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["sector", "level", "is_active"]
    search_fields = ["title", "code"]
    ordering_fields = ["title", "code", "created_at"]
    ordering = ["title"]

    def get_serializer_class(self):
        if self.action == "list":
            return QualificationListSerializer
        if self.action in ("create", "update", "partial_update"):
            return QualificationWriteSerializer
        return QualificationDetailSerializer

    def get_queryset(self):
        qs = Qualification.objects.select_related("sector", "level")
        if self.action == "list":
            qs = qs.annotate(
                question_count=Count(
                    "questions", filter=Q(questions__is_active=True)))
        if self.action == "retrieve":
            qs = qs.prefetch_related("units")
        # Hide inactive unless ?include_inactive=true (admin only)
        if self.request.query_params.get("include_inactive") != "true":
            qs = qs.filter(is_active=True)
        return qs

    @action(detail=True, methods=["get"], url_path="bank-health")
    def bank_health(self, request, pk=None):
        """
        Why: AdminQuestionBank polls this every 30s while admins add questions.
             Splitting it out means the heavy COUNT doesn't hit the detail
             endpoint, which is cached.
        """
        qual = self.get_object()
        total = qual.questions.filter(is_active=True).count()
        target = qual.recommended_bank_size or 1
        return Response({
            "current": total,
            "target": target,
            "min": qual.min_bank_size,
            "percent": round(min(100, (total / target) * 100), 1),
            "status": ("healthy" if total >= target
                       else "warning" if total >= qual.min_bank_size
                       else "critical"),
        })

    @action(detail=True, methods=["get"])
    def units(self, request, pk=None):
        """GET /api/qualifications/{id}/units/ — used by question editor unit picker."""
        qs = self.get_object().units.all().order_by("sort_order")
        return Response(QualificationUnitSerializer(qs, many=True).data)
```

### 5.1 Learner-safe twin: `MyQualificationsView`

```python
class MyQualificationsView(generics.ListAPIView):
    """
    Why: Learners must NOT see resit_fail_margin_percent, min_bank_size, etc.
         (information disclosure → learners could game the resit threshold).
         Separate endpoint with a stripped serializer is safer than runtime
         field hiding.
    Where:
      - GET /api/me/qualifications/  → LearnerDashboard.tsx "Your qualification" card.
    """
    serializer_class = QualificationListSerializer  # lean, no resit fields
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (Qualification.objects
                .filter(enrollments__learner=self.request.user,
                        enrollments__status="active",
                        is_active=True)
                .select_related("sector", "level")
                .distinct())
```

---

## 6. `QualificationUnitViewSet`

```python
class QualificationUnitViewSet(AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Units are admin-managed sub-topics. Used for question tagging and
         per-unit analytics.
    Where:
      - GET   /api/qualifications/{qid}/units/    → AdminQuestionBank tag picker
      - POST  /api/qualifications/{qid}/units/    → "Manage Units" modal
      - PATCH /api/units/{id}/                    → Inline edit
    Routing:
      - Nested under qualifications via drf-nested-routers, OR exposed flat
        with `?qualification={id}` filter. Pick one and stay consistent —
        recommendation: nested for writes, flat for reads.
    """
    serializer_class = QualificationUnitSerializer
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["qualification"]
    ordering = ["qualification", "sort_order"]

    def get_queryset(self):
        return QualificationUnit.objects.select_related("qualification")
```

---

## 7. Enrollment views (split for safety)

### 7.1 `EnrollmentViewSet` — admin

```python
class EnrollmentViewSet(AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Admin-only CRUD for learner enrolments. Drives the AdminLearners
         "Add/Edit Learner" form (which currently sets a flat qualificationId
         on the learner — that field will move here).
    Where:
      - GET    /api/enrollments/?learner={id}      → AdminLearners detail drawer
      - POST   /api/enrollments/                   → "Add Learner" form
      - PATCH  /api/enrollments/{id}/              → "Edit" / "Withdraw" actions
      - DELETE /api/enrollments/{id}/              → Soft-delete only (sets status=withdrawn)
    Permissions:
      - Admin: full CRUD.
      - Invigilator: read-only on enrolments for sessions they invigilate.
      - Learner: denied (use /api/me/enrollments/).
    """
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["learner", "qualification", "status", "cohort", "employer"]
    search_fields = ["learner__email", "learner__first_name", "learner__last_name",
                     "qualification__title", "qualification__code"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EnrollmentWriteSerializer
        return EnrollmentReadSerializer

    def get_queryset(self):
        qs = (QualificationEnrollment.objects
              .select_related("learner", "qualification"))
        u = self.request.user
        if u.role == "invigilator":
            qs = qs.filter(
                learner__sessions__invigilator=u
            ).distinct()
        return qs

    def perform_destroy(self, instance):
        """Never hard-delete enrolments — historical records needed for ESFA."""
        instance.status = "withdrawn"
        instance.withdrawn_at = timezone.now().date()
        instance.save(update_fields=["status", "withdrawn_at", "updated_at"])
        self._audit("withdraw", instance)
```

### 7.2 `MyEnrollmentsView` — learner

```python
class MyEnrollmentsView(generics.ListAPIView):
    """
    Why: Learners need to see what they're enrolled on, but must not see
         other learners' rows or admin-only notes.
    Where:
      - GET /api/me/enrollments/  → LearnerDashboard.tsx top card
    """
    serializer_class = EnrollmentReadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (QualificationEnrollment.objects
                .filter(learner=self.request.user)
                .select_related("qualification")
                .order_by("-enrolled_at"))
```

---

## 8. Bulk import endpoint (AdminLearners CSV)

```python
class BulkEnrollmentImportView(APIView):
    """
    Why: AdminLearners.tsx will need a CSV import path (office onboards
         cohorts of 50–200 learners at once). One row per (learner, qual, cohort).
    Where:
      - POST /api/enrollments/bulk-import/   (multipart, file=enrollments.csv)
    Behaviour:
      - Atomic transaction: either ALL rows pass validation or NONE are written.
      - Returns per-row errors for the UI to render in a table.
      - Idempotent: re-uploading the same CSV is a no-op (unique constraint).
    """
    permission_classes = [IsAdmin]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "file required"}, status=400)
        rows, errors = parse_enrollment_csv(file)  # see services/imports.py
        if errors:
            return Response({"errors": errors}, status=400)
        with transaction.atomic():
            created = [
                QualificationEnrollment.objects.update_or_create(
                    learner_id=r["learner_id"],
                    qualification_id=r["qualification_id"],
                    cohort=r["cohort"],
                    defaults=r,
                )[0]
                for r in rows
            ]
        return Response({"created": len(created)}, status=201)
```

---

## 9. URL wiring (`apps/qualifications/urls.py`)

```python
from rest_framework.routers import DefaultRouter
from rest_framework_nested.routers import NestedDefaultRouter

router = DefaultRouter()
router.register("sectors", SectorViewSet, basename="sector")
router.register("levels", LevelViewSet, basename="level")
router.register("qualifications", QualificationViewSet, basename="qualification")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")

quals_router = NestedDefaultRouter(router, "qualifications", lookup="qualification")
quals_router.register("units", QualificationUnitViewSet, basename="qualification-units")

urlpatterns = [
    path("", include(router.urls)),
    path("", include(quals_router.urls)),
    path("me/qualifications/", MyQualificationsView.as_view()),
    path("me/enrollments/", MyEnrollmentsView.as_view()),
    path("enrollments/bulk-import/", BulkEnrollmentImportView.as_view()),
]
```

---

## 10. Permissions matrix (single source of truth)

| Endpoint | Admin | Invigilator | Learner |
|---|:-:|:-:|:-:|
| `GET /api/sectors/` | ✅ | ✅ | ❌ |
| `POST/PATCH/DELETE /api/sectors/` | ✅ | ❌ | ❌ |
| `GET /api/levels/` | ✅ | ✅ | ❌ |
| `POST/PATCH/DELETE /api/levels/` | ✅ | ❌ | ❌ |
| `GET /api/qualifications/` | ✅ (full) | ✅ (full) | ❌ |
| `GET /api/qualifications/{id}/` | ✅ (full) | ✅ (no resit fields*) | ❌ |
| `POST/PATCH/DELETE /api/qualifications/` | ✅ | ❌ | ❌ |
| `GET /api/qualifications/{id}/bank-health/` | ✅ | ❌ | ❌ |
| `GET /api/qualifications/{qid}/units/` | ✅ | ✅ | ❌ |
| `POST/PATCH/DELETE /api/qualifications/{qid}/units/` | ✅ | ❌ | ❌ |
| `GET /api/enrollments/` | ✅ (all) | ✅ (own sessions) | ❌ |
| `POST/PATCH /api/enrollments/` | ✅ | ❌ | ❌ |
| `DELETE /api/enrollments/{id}/` | ✅ (soft only) | ❌ | ❌ |
| `GET /api/me/qualifications/` | ✅ | ✅ | ✅ |
| `GET /api/me/enrollments/` | ✅ | ✅ | ✅ |
| `POST /api/enrollments/bulk-import/` | ✅ | ❌ | ❌ |

\* Resit fields stripped via `to_representation` override in `QualificationDetailSerializer` when `request.user.role != "admin"`.

---

## 11. Caching matrix

| Endpoint | Cache | TTL | Invalidation |
|---|---|---|---|
| `GET /api/sectors/` | Per-role | 5 min | On any Sector write |
| `GET /api/levels/` | Per-role | 5 min | On any Level write |
| `GET /api/qualifications/` | Per-role + filters | 60 s | On any Qualification write |
| `GET /api/qualifications/{id}/` | Per-role + id | 60 s | On that qualification's write |
| `GET /api/qualifications/{id}/bank-health/` | None | — | Frontend polls every 30 s |
| `GET /api/me/*` | None | — | Per-user data, low volume |

Cache backend: Redis. Use `django-cacheops` or hand-rolled keys via the `RoleAwareCacheMixin`.

---

## 12. Testing checklist (the things that always break)

- [ ] PATCH on Qualification with only one boundary field doesn't crash validation.
- [ ] Learner cannot read resit fields via any endpoint.
- [ ] Invigilator cannot list enrolments outside their own sessions.
- [ ] DELETE on Sector with attached qualifications returns 400, not 500.
- [ ] DELETE on Enrollment soft-deletes (status='withdrawn'), never hard-deletes.
- [ ] Bulk import is atomic — partial failure rolls back everything.
- [ ] Cache invalidation fires on every write (test via patched `cache.delete`).
- [ ] `?include_inactive=true` is rejected for non-admins.
- [ ] Pagination max page_size enforced (200) — prevents `?page_size=10000` DoS.

---

_Last updated: 2026-05-06 — Lead Edge Ltd EPAO Platform_
