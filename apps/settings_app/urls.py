from django.urls import path

from .views import SystemSettingsView, BrandMiniView


urlpatterns = [
    path("", SystemSettingsView.as_view(), name="system-settings"),
    path("brand-mini/", BrandMiniView.as_view(), name="brand-mini"), 
]
