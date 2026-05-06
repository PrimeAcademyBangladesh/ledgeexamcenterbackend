"""
apps/qualifications/urls.py
Lead Edge Ltd EPAO Exam Platform

Mount in your project's root urls.py:
    path("api/", include("apps.qualifications.urls")),
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SectorViewSet,
    LevelViewSet,
    QualificationViewSet,
    QualificationUnitViewSet,
    EnrollmentViewSet,
    MyQualificationsView,
    MyEnrollmentsView,
    BulkEnrollmentImportView,
)

router = DefaultRouter()
router.register("sectors", SectorViewSet, basename="sector")
router.register("levels", LevelViewSet, basename="level")
router.register("qualifications", QualificationViewSet, basename="qualification")
router.register("units", QualificationUnitViewSet, basename="qualification-unit")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")

urlpatterns = [

    path("enrollments/bulk-import/", BulkEnrollmentImportView.as_view(),
         name="enrollment-bulk-import"),

    # Learner-facing endpoints
    path("me/qualifications/", MyQualificationsView.as_view(),
         name="my-qualifications"),
    path("me/enrollments/", MyEnrollmentsView.as_view(),
         name="my-enrollments"),

    path("", include(router.urls)),
]

# ────────────────────────────────────────────────────────────
#  Resulting URL map
# ────────────────────────────────────────────────────────────
#  GET    /api/sectors/
#  POST   /api/sectors/
#  GET    /api/sectors/{id}/
#  PATCH  /api/sectors/{id}/
#  DELETE /api/sectors/{id}/
#
#  GET    /api/levels/
#  POST   /api/levels/
#  GET    /api/levels/{id}/
#  PATCH  /api/levels/{id}/
#
#  GET    /api/qualifications/?is_active=true&page_size=200
#  POST   /api/qualifications/
#  GET    /api/qualifications/{id}/
#  PATCH  /api/qualifications/{id}/
#  DELETE /api/qualifications/{id}/
#  GET    /api/qualifications/{id}/bank-health/
#  GET    /api/qualifications/{id}/units/
#
#  GET    /api/units/?qualification={id}
#  POST   /api/units/
#  PATCH  /api/units/{id}/
#  DELETE /api/units/{id}/
#
#  GET    /api/enrollments/?learner={id}
#  POST   /api/enrollments/
#  PATCH  /api/enrollments/{id}/
#  DELETE /api/enrollments/{id}/         (soft-delete → status=withdrawn)
#  POST   /api/enrollments/bulk-import/  (multipart, file=enrollments.csv)
#
#  GET    /api/me/qualifications/        (learner-safe)
#  GET    /api/me/enrollments/           (learner-safe)