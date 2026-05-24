"""
Lead Edge Ltd — Questions URL config

Mounted under "/questions/" by the project urls.py — router prefixes are flat.

Resulting endpoints:
    GET/POST            /questions/
    GET/PUT/PATCH/DEL   /questions/<id>/

    GET/POST            /questions/scenarios/
    GET/PUT/PATCH/DEL   /questions/scenarios/<id>/
"""

from rest_framework.routers import DefaultRouter

from .views import QuestionViewSet, ScenarioViewSet

router = DefaultRouter()
router.register(r"scenarios", ScenarioViewSet, basename="scenario")
router.register(r"", QuestionViewSet, basename="question")

urlpatterns = router.urls
