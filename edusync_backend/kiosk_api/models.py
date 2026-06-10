from django.contrib.auth.models import User
from django.db import models


class Course(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    target_batch_year = models.CharField(max_length=2)
    target_department = models.CharField(max_length=3)
    assigned_teacher = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.code} - {self.name} (Batch '{self.target_batch_year})"


class Student(models.Model):
    roll_number = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    session_pin = models.CharField(max_length=10)

    @property
    def batch_year(self):
        return self.roll_number[0:2]

    @property
    def department_code(self):
        if len(self.roll_number) >= 8:
            return self.roll_number[5:8]
        return "".join(character for character in self.roll_number if character.isalpha())

    def __str__(self):
        return f"{self.roll_number} - {self.name}"


class Exam(models.Model):
    title = models.CharField(max_length=200)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True)
    duration_seconds = models.IntegerField(default=7200)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        course_code = self.course.code if self.course else "No Course"
        return f"{self.title} ({course_code})"


class ExamAttempt(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    is_locked = models.BooleanField(default=False)
    admin_override = models.BooleanField(default=False)

    class Meta:
        unique_together = ("student", "exam")

    def __str__(self):
        return f"{self.student.roll_number} - {self.exam.title} | Locked: {self.is_locked}"


class Submission(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    code_content = models.TextField(blank=True, null=True)
    violation_count = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.roll_number} | {self.exam.title} | Strikes: {self.violation_count}"
