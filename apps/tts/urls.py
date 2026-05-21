from django.urls import path
from .views import TTSSpeakView

urlpatterns = [
    path("speak/", TTSSpeakView.as_view(), name="tts-speak"),
]
