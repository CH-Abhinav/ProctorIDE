from django.contrib import admin

from .models import Course, Exam, ExamAttempt, Student, Submission


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "target_batch_year", "target_department", "assigned_teacher")
    list_filter = ("target_batch_year", "target_department", "assigned_teacher")
    search_fields = ("code", "name")


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "duration_seconds", "is_active", "created_at")
    list_filter = ("is_active", "course")
    search_fields = ("title", "course__code", "course__name")
    actions = ["make_inactive", "make_active"]

    @admin.action(description="Deactivate selected exams (Stop Exam)")
    def make_inactive(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Activate selected exams (Start Exam)")
    def make_active(self, request, queryset):
        queryset.update(is_active=True)


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "is_locked", "admin_override")
    list_filter = ("is_locked", "admin_override", "exam")
    search_fields = ("student__roll_number", "student__name", "exam__title")
    actions = ["unlock_attempts", "toggle_override"]

    @admin.action(description="Unlock selected attempts")
    def unlock_attempts(self, request, queryset):
        queryset.update(is_locked=False)

    @admin.action(description="Enable admin override")
    def toggle_override(self, request, queryset):
        queryset.update(admin_override=True)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("roll_number", "name", "session_pin")
    search_fields = ("roll_number", "name")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "violation_count", "submitted_at")
    list_filter = ("exam",)
    search_fields = ("student__roll_number", "student__name", "exam__title")
