"""
URL config — mount under the project root urls.py:

    path("api/", include("apps.invigilators.urls")),
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    InvigilatorByProviderCodeView,
    InvigilatorViewSet,
    ProviderCentreViewSet,
    ProviderDropDownView,
)

router = DefaultRouter()
router.register(r"invigilators", InvigilatorViewSet, basename="invigilator")
router.register(r"provider-centres", ProviderCentreViewSet, basename="provider-centre")

urlpatterns = [
    path("", include(router.urls)),
    path("invigilators/dropdown/", ProviderDropDownView.as_view(), name="invigilator-dropdown"),
    path(
        "invigilators/by-code/<str:code>/",
        InvigilatorByProviderCodeView.as_view(),
        name="invigilator-by-code",
    ),
]
