from django.urls import path

from . import views


urlpatterns = [
    path("login/", views.portal_login, name="portal_login"),
    path("logout/", views.portal_logout, name="portal_logout"),
    path("", views.dashboard_home, name="dashboard_home"),
    path("exams/<int:exam_id>/", views.exam_detail, name="exam_detail"),
    path(
        "submissions/<int:submission_id>/",
        views.submission_detail,
        name="submission_detail",
    ),
]
