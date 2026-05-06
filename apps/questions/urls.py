"""
Lead Edge Ltd — Questions URL config

Mounted under "/questions/" by the project urls.py — router prefixes are flat.

Resulting endpoints:
    GET/POST            /questions/
    GET/PUT/PATCH/DEL   /questions/<id>/
    POST                /questions/bulk-import/
"""

from rest_framework.routers import DefaultRouter

from .views import QuestionViewSet

router = DefaultRouter()
router.register(r"", QuestionViewSet, basename="question")

urlpatterns = router.urls
