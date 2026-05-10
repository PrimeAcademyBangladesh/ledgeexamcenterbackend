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
)

router = DefaultRouter()
router.register("sectors", SectorViewSet, basename="sector")
router.register("levels", LevelViewSet, basename="level")
router.register("qualifications", QualificationViewSet, basename="qualification")
router.register("units", QualificationUnitViewSet, basename="qualification-unit")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")

urlpatterns = [

    path("me/qualifications/", MyQualificationsView.as_view(),
         name="my-qualifications"),
    path("me/enrollments/", MyEnrollmentsView.as_view(),
         name="my-enrollments"),

    path("", include(router.urls)),
]
