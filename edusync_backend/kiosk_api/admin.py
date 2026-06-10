from django.contrib import admin

from .models import Exam, Student, Submission


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "subject_code",
        "examiner",
        "duration_seconds",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "examiner")
    search_fields = ("title", "subject_code")
    actions = ["make_inactive", "make_active"]

    @admin.action(description="Deactivate selected exams (Stop Exam)")
    def make_inactive(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Activate selected exams (Start Exam)")
    def make_active(self, request, queryset):
        queryset.update(is_active=True)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("roll_number", "name", "session_pin")
    search_fields = ("roll_number", "name")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "violation_count", "submitted_at")
    list_filter = ("exam",)
    search_fields = ("student__roll_number", "student__name")
