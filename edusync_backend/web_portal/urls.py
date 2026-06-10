from django.urls import path

from . import views


urlpatterns = [
    path("login/", views.portal_login, name="portal_login"),
    path("logout/", views.portal_logout, name="portal_logout"),
    path("", views.dashboard_home, name="dashboard_home"),
    path("exams/<int:exam_id>/", views.exam_detail, name="exam_detail"),
    path(
        "download/<int:submission_id>/",
        views.download_submission,
        name="download_submission",
    ),
    path(
        "submissions/<int:submission_id>/",
        views.submission_detail,
        name="submission_detail",
    ),
]
