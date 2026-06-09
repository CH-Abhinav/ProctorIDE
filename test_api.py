import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "edusync_backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edusync_core.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from kiosk_api.models import Exam, Student, Submission


settings.ALLOWED_HOSTS = ["testserver"]


class KioskApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Submission.objects.all().delete()
        Exam.objects.all().delete()
        Student.objects.all().delete()
        User.objects.all().delete()

        cls.examiner = User.objects.create_user(
            username="examiner",
            password="secure-password-123",
        )
        cls.student = Student.objects.create(
            roll_number="R001",
            name="Aarav",
            session_pin="1234",
        )
        cls.exam = Exam.objects.create(
            title="Database Systems",
            examiner=cls.examiner,
            subject_code="CS-201",
            duration_seconds=3600,
            is_active=True,
        )

    def test_login_returns_session_token_for_active_exam(self):
        response = self.client.post(
            reverse("kiosk_login"),
            {
                "subject_code": "CS-201",
                "roll_number": "R001",
                "session_pin": "1234",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("session_token", response.data)
        self.assertIsInstance(response.data["session_token"], str)
        self.assertGreater(len(response.data["session_token"]), 10)
        self.assertEqual(response.data["student_name"], "Aarav")
        self.assertEqual(response.data["exam"]["subject_code"], "CS-201")

    def test_login_rejects_inactive_pin(self):
        response = self.client.post(
            reverse("kiosk_login"),
            {
                "subject_code": "CS-201",
                "roll_number": "R001",
                "session_pin": "9999",
            },
            format="json",
        )

        self.assertIn(response.status_code, {status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED})
        self.assertIn("error", response.data)

    def test_submit_creates_submission_record(self):
        login_response = self.client.post(
            reverse("kiosk_login"),
            {
                "subject_code": "CS-201",
                "roll_number": "R001",
                "session_pin": "1234",
            },
            format="json",
        )

        payload = {
            "roll_number": "R001",
            "code_content": "print('hello from proctor ide')",
            "violation_count": 2,
            "session_token": login_response.data["session_token"],
        }
        response = self.client.post(reverse("submit_exam"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Submission.objects.count(), 1)

        submission = Submission.objects.select_related("student", "exam").get()
        self.assertEqual(submission.student, self.student)
        self.assertEqual(submission.exam, self.exam)
        self.assertEqual(submission.code_content, payload["code_content"])
        self.assertEqual(submission.violation_count, 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
