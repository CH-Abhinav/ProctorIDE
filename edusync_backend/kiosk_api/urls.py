from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.kiosk_login, name='kiosk_login'),
    path('submit/', views.submit_exam, name='submit_exam'),
]