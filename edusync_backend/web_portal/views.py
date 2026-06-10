import os

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import FileResponse, Http404
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from kiosk_api.models import Exam, Submission


def portal_login(request):
    if request.user.is_authenticated:
        return redirect("dashboard_home")

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("dashboard_home")

    return render(request, "web_portal/login.html", {"form": form})


def portal_logout(request):
    logout(request)
    return redirect("portal_login")


@login_required(login_url="portal_login")
def dashboard_home(request):
    exams = (
        Exam.objects.filter(examiner=request.user)
        .annotate(submission_total=Count("submission"))
        .order_by("-is_active", "subject_code", "title")
    )
    return render(request, "web_portal/dashboard.html", {"exams": exams})


@login_required(login_url="portal_login")
def exam_detail(request, exam_id):
    exam = get_object_or_404(
        Exam.objects.filter(examiner=request.user).annotate(
            submission_total=Count("submission")
        ),
        pk=exam_id,
    )
    submissions = (
        Submission.objects.filter(exam=exam)
        .select_related("student")
        .order_by("-violation_count", "-submitted_at", "student__roll_number")
    )
    return render(
        request,
        "web_portal/exam_detail.html",
        {
            "exam": exam,
            "submissions": submissions,
        },
    )


@login_required(login_url="portal_login")
def submission_detail(request, submission_id):
    submission = get_object_or_404(
        Submission.objects.select_related("student", "exam").filter(
            exam__examiner=request.user
        ),
        pk=submission_id,
    )
    return render(
        request,
        "web_portal/submission.html",
        {"submission": submission},
    )


@login_required(login_url="portal_login")
def download_submission(request, submission_id):
    submission = get_object_or_404(
        Submission.objects.select_related("exam").filter(
            exam__examiner=request.user
        ),
        pk=submission_id,
    )
    file_path = submission.code_content

    if file_path and os.path.exists(file_path):
        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=os.path.basename(file_path),
        )

    raise Http404("Zip file not found on server.")
