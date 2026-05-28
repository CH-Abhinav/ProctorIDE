from rest_framework import serializers
from .models import Student, Exam

class ExamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = ['title', 'subject_code', 'duration_seconds', 'is_active']
