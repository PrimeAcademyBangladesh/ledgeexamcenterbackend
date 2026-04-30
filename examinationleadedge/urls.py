from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path('admin/', admin.site.urls),
    path('users/', include('apps.users.urls')),
    path('sessions/', include('apps.sessions.urls')),
    path('adjustments/', include('apps.adjustments.urls')),
    path('invigilators/', include('apps.invigilators.urls')),
    path('learner/', include('apps.learners.urls')),
    path('results/', include('apps.results.urls')),
    path('retakes/', include('apps.retakes.urls')),
    path('questions/', include('apps.questions.urls')),
    path('reports/', include('apps.reports.urls')),
    path('qualifications/', include('apps.qualifications.urls')),
    path('exams/', include('apps.exams.urls')),
    path('integrity/', include('apps.integrity.urls')),
]
