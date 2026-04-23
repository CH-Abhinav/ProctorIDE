from django.contrib import admin
from .models import Student, Exam, Submission

admin.site.register(Student)
admin.site.register(Exam)
admin.site.register(Submission)