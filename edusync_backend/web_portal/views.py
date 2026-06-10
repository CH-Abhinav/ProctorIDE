import os

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from kiosk_api.models import Exam, Submission


def _is_teacher(user):
    return user.is_authenticated and user.groups.filter(name="Teacher").exists()


def _is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def _exam_queryset_for_user(user):
    queryset = Exam.objects.select_related("course", "course__assigned_teacher").annotate(
        submission_total=Count("submission")
    )
    if _is_admin(user):
        return queryset.order_by("-is_active", "course__code", "title")
    if _is_teacher(user):
        return queryset.filter(course__assigned_teacher=user).order_by(
            "-is_active",
            "course__code",
            "title",
        )
    return queryset.none()


def _can_access_exam(user, exam):
    if _is_admin(user):
        return True
    if _is_teacher(user):
        return exam.course and exam.course.assigned_teacher_id == user.id
    return False


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
    exams = _exam_queryset_for_user(request.user)
    if not _is_admin(request.user) and not _is_teacher(request.user):
        return HttpResponseForbidden("You do not have permission to access the portal dashboard.")

    return render(
        request,
        "web_portal/dashboard.html",
        {
            "exams": exams,
            "is_admin": _is_admin(request.user),
            "is_teacher": _is_teacher(request.user),
        },
    )


@login_required(login_url="portal_login")
def exam_detail(request, exam_id):
    exam = get_object_or_404(_exam_queryset_for_user(request.user), pk=exam_id)
    if not _can_access_exam(request.user, exam):
        return HttpResponseForbidden("You do not have permission to view this exam.")

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
            "is_admin": _is_admin(request.user),
            "is_teacher": _is_teacher(request.user),
        },
    )


@login_required(login_url="portal_login")
def submission_detail(request, submission_id):
    submission = get_object_or_404(
        Submission.objects.select_related("student", "exam", "exam__course"),
        pk=submission_id,
    )
    if not _can_access_exam(request.user, submission.exam):
        return HttpResponseForbidden("You do not have permission to view this submission.")

    return render(
        request,
        "web_portal/submission.html",
        {
            "submission": submission,
            "is_admin": _is_admin(request.user),
            "is_teacher": _is_teacher(request.user),
        },
    )


@login_required(login_url="portal_login")
def download_submission(request, submission_id):
    submission = get_object_or_404(
        Submission.objects.select_related("exam", "exam__course"),
        pk=submission_id,
    )
    if not _can_access_exam(request.user, submission.exam):
        return HttpResponseForbidden("You do not have permission to download this submission.")

    file_path = submission.code_content

    if file_path and os.path.exists(file_path):
        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=os.path.basename(file_path),
        )

    raise Http404("Zip file not found on server.")
