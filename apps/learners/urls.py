"""
apps/learners/urls.py
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    LearnerViewSet,
    LearnerByUlnView,
    EnrollmentViewSet,
    MyEnrollmentsView,
    ReasonableAdjustmentViewSet,
)

router = DefaultRouter()
router.register(r"", LearnerViewSet, basename="learner")
router.register(r"enrollments", EnrollmentViewSet, basename="enrollment")
router.register(r"reasonable-adjustments", ReasonableAdjustmentViewSet, basename="reasonable-adjustment")

urlpatterns = [
    path("", include(router.urls)),
    path("by-uln/<str:uln>/", LearnerByUlnView.as_view(), name="learner-by-uln"),
    path("me/enrollments/", MyEnrollmentsView.as_view(), name="my-enrollments"),
]
