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

router.register(r"provider-centres", ProviderCentreViewSet, basename="provider-centre")
router.register(r"", InvigilatorViewSet, basename="invigilator")

urlpatterns = [
    path("dropdown/", ProviderDropDownView.as_view(), name="invigilator-dropdown"),
    path(
        "by-code/<str:code>/",
        InvigilatorByProviderCodeView.as_view(),
        name="invigilator-by-code",
    ),
    path("", include(router.urls)),
]
