from rest_framework import serializers

from .models import Exam


class ExamSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)

    class Meta:
        model = Exam
        fields = ["title", "course", "course_code", "duration_seconds", "is_active"]
