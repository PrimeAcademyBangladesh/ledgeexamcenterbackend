from django.urls import path

from .views import MarksheetView, ReportExportView, ReportViewSet


report_list = ReportViewSet.as_view({"get": "list"})
report_detail = ReportViewSet.as_view({"get": "retrieve"})

urlpatterns = [
    # Specific paths before the detail/list routes.
    path("export/", ReportExportView.as_view(), name="report-export"),
    path("<uuid:pk>/marksheet/", MarksheetView.as_view(), name="report-marksheet"),
    path("<uuid:pk>/", report_detail, name="report-detail"),
    path("", report_list, name="report-list"),
]
