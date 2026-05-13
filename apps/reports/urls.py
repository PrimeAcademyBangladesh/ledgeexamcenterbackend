from django.urls import path

from .views import ReportExportView, ReportViewSet


report_list = ReportViewSet.as_view({"get": "list"})

urlpatterns = [
    path("export/", ReportExportView.as_view(), name="report-export"),
    path("", report_list, name="report-list"),
]
