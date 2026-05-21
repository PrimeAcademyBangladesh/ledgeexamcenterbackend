from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('users/', include('apps.users.urls')),
    path('adjustments/', include('apps.adjustments.urls')),
    path('invigilators/', include('apps.invigilators.urls')),
    path('learner/', include('apps.learners.urls')),
    path('results/', include('apps.results.urls')),
    path('retakes/', include('apps.retakes.urls')),
    path('settings/', include('apps.settings_app.urls')),
    path('questions/', include('apps.questions.urls')),
    path('reports/', include('apps.reports.urls')),
    path('', include('apps.qualifications.urls')),
    path('exams/', include('apps.exams.urls')),
    path('integrity/', include('apps.integrity.urls')),
    path('api/tts/', include('apps.tts.urls')),
]
