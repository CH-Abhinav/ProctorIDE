from django.db import models

class Student(models.Model):
    roll_number = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    session_pin = models.CharField(max_length=10)

    def __str__(self):
        return f"{self.roll_number} - {self.name}"

class Exam(models.Model):
    title = models.CharField(max_length=200)
    duration_seconds = models.IntegerField(default=7200)
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return self.title

class Submission(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    
    # Store the code directly from the Tkinter text widget
    code_content = models.TextField(blank=True, null=True)
    
    # The security tripwire data
    violation_count = models.IntegerField(default=0)
    
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.roll_number} | {self.exam.title} | Strikes: {self.violation_count}"