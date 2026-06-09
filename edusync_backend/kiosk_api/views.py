import os
import os
import secrets

from django.http import JsonResponse
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.response import Response
from rest_framework.parsers import FormParser, MultiPartParser
from django.db import transaction

from .models import Exam, Student, Submission


def _get_active_exam_for_submission(student):
    active_exams = list(Exam.objects.filter(is_active=True).order_by("-id"))
    if not active_exams:
        return None, Response(
            {"error": "No active exam right now."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if len(active_exams) == 1:
        return active_exams[0], None

    latest_submission = (
        Submission.objects.filter(student=student, exam__is_active=True)
        .select_related("exam")
        .order_by("-submitted_at")
        .first()
    )
    if latest_submission is None:
        return None, Response(
            {
                "error": (
                    "Multiple active exams were found and the student's exam "
                    "could not be determined."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    return latest_submission.exam, None


@api_view(['POST'])
def kiosk_login(request):
    subject_code = (request.data.get('subject_code') or '').strip()
    roll_number = (request.data.get('roll_number') or '').strip()
    session_pin = (request.data.get('session_pin') or '').strip()

    if not subject_code or not roll_number or not session_pin:
        return Response(
            {
                "error": (
                    "subject_code, roll_number, and session_pin are required."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        student = Student.objects.get(roll_number=roll_number, session_pin=session_pin)
    except Student.DoesNotExist:
        return Response(
            {"error": "Invalid Roll Number or PIN"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    active_exam = (
        Exam.objects.filter(is_active=True, subject_code=subject_code)
        .order_by("-id")
        .first()
    )
    if not active_exam:
        return Response(
            {"error": "No active exam found for this subject code."},
            status=status.HTTP_404_NOT_FOUND,
        )

    session_token = secrets.token_urlsafe(24)

    return Response({
        "student_name": student.name,
        "session_token": session_token,
        "exam": {
            "title": active_exam.title,
            "subject_code": active_exam.subject_code,
            "duration_seconds": active_exam.duration_seconds,
        },
    })


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def submit_exam(request):
    roll_number = (request.data.get('roll_number') or '').strip()
    violations = request.data.get('violation_count', 0)
    session_token = (request.data.get('session_token') or '').strip()
    uploaded_file = request.FILES.get('file')

    if not roll_number:
        return Response(
            {"error": "roll_number is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if uploaded_file is None:
        return Response(
            {"error": "file is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        violations = int(violations)
    except (TypeError, ValueError):
        return Response(
            {"error": "violation_count must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        student = Student.objects.get(roll_number=roll_number)
    except Student.DoesNotExist:
        return Response(
            {"error": "Student not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    active_exam, error_response = _get_active_exam_for_submission(student)
    if error_response is not None:
        return error_response

    submissions_dir = os.path.join(settings.BASE_DIR, "submissions")
    os.makedirs(submissions_dir, exist_ok=True)

    safe_roll_number = "".join(
        character for character in roll_number
        if character.isalnum() or character in ("-", "_")
    ) or "submission"
    zip_path = os.path.join(submissions_dir, f"{safe_roll_number}_submission.zip")

    with open(zip_path, "wb+") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    with transaction.atomic():
        Submission.objects.create(
            student=student,
            exam=active_exam,
            code_content=zip_path,
            violation_count=violations,
        )
    return Response({"message": "Exam submitted successfully!"})


def upload_exam_zip(request):
    if request.method == "POST":
        zip_file = request.FILES["file"]
        roll_number = request.POST.get("roll_number")

        os.makedirs("submissions", exist_ok=True)
        with open(f"submissions/{roll_number}_submission.zip", "wb+") as destination:
            for chunk in zip_file.chunks():
                destination.write(chunk)

        return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)
