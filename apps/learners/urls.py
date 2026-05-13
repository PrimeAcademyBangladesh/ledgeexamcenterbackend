"""
apps/learners/urls.py
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    LearnerViewSet,
    LearnerByUlnView,
    EnrollmentViewSet,
    GenerateUlnView,
    MyEnrollmentsView,
    ReasonableAdjustmentViewSet,
    LearnerDropDownViewSet
)

router = DefaultRouter()
router.register(r"learners", LearnerViewSet, basename="learner")
router.register(r"enrollments", EnrollmentViewSet, basename="enrollment")
router.register(r"reasonable-adjustments", ReasonableAdjustmentViewSet, basename="reasonable-adjustment")

urlpatterns = [
    # Specific paths must come before the router include — otherwise
    # `learners/<pk>/` swallows `learners/generate-uln/` and `learners/by-uln/...`.
    path("learners/dropdown/", LearnerDropDownViewSet.as_view(), name="learner-dropdown"),
    path("learners/generate-uln/", GenerateUlnView.as_view(), name="learner-generate-uln"),
    path("learners/by-uln/<str:uln>/", LearnerByUlnView.as_view(), name="learner-by-uln"),
    path("me/enrollments/", MyEnrollmentsView.as_view(), name="my-enrollments"),
    path("", include(router.urls)),
]
