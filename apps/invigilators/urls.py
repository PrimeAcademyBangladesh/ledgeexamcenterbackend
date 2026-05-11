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
# Register provider-centres BEFORE the invigilators detail route so DRF
# emits the more-specific pattern first. Otherwise `provider-centres` would
# get captured as `<pk>` by the InvigilatorViewSet detail route.
router.register(r"provider-centres", ProviderCentreViewSet, basename="provider-centre")
router.register(r"", InvigilatorViewSet, basename="invigilator")

urlpatterns = [
    # Standalone paths first — otherwise the InvigilatorViewSet detail route
    # `^(?P<pk>[^/.]+)/$` greedily captures `dropdown` (and any other single
    # literal segment) as `pk`.
    path("dropdown/", ProviderDropDownView.as_view(), name="invigilator-dropdown"),
    path(
        "by-code/<str:code>/",
        InvigilatorByProviderCodeView.as_view(),
        name="invigilator-by-code",
    ),
    path("", include(router.urls)),
]
