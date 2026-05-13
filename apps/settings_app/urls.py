from django.urls import path

from .views import SystemSettingsView


urlpatterns = [
    path("", SystemSettingsView.as_view(), name="system-settings"),
]
