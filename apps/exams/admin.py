from django.contrib import admin
from .models import Exam, ExamCentre, ExamSession


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "date")
    search_fields = ("name", "code")


@admin.register(ExamCentre)
class ExamCentreAdmin(admin.ModelAdmin):
    list_display = ("name", "location")
    search_fields = ("name", "location")


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ("exam", "centre", "start_time", "end_time")
    list_filter = ("exam", "centre")
    search_fields = ("exam__name", "centre__name")
