from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Student, Exam, Submission
from .serializers import ExamSerializer

@api_view(['POST'])
def kiosk_login(request):
    roll_number = request.data.get('roll_number')
    session_pin = request.data.get('session_pin')

    # 1. Check if the student exists and PIN is correct
    try:
        student = Student.objects.get(roll_number=roll_number, session_pin=session_pin)
    except Student.DoesNotExist:
        return Response({"error": "Invalid Roll Number or PIN"}, status=status.HTTP_401_UNAUTHORIZED)

    # 2. Find the active exam (we assume only 1 exam is active at a time for labs)
    active_exam = Exam.objects.filter(is_active=True).first()
    if not active_exam:
        return Response({"error": "No active exam right now"}, status=status.HTTP_404_NOT_FOUND)

    # 3. Success! Send back the student name and the exam timer duration
    return Response({
        "message": "Login successful",
        "student_name": student.name,
        "exam": ExamSerializer(active_exam).data
    })

@api_view(['POST'])
def submit_exam(request):
    roll_number = request.data.get('roll_number')
    code = request.data.get('code_content')
    violations = request.data.get('violation_count', 0)

    try:
        student = Student.objects.get(roll_number=roll_number)
        active_exam = Exam.objects.filter(is_active=True).first()
        
        # Save their work to the database!
        Submission.objects.create(
            student=student,
            exam=active_exam,
            code_content=code,
            violation_count=violations
        )
        return Response({"message": "Exam submitted successfully!"})
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)