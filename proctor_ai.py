import threading
import time

import cv2
import mediapipe as mp
import numpy as np


class AIProctor:
    def __init__(self):
        self.is_running = False
        self.latest_frame = None
        self.violation_strikes = 0
        self.last_seen_time = None
        self.lock = threading.Lock()

    def run_camera_loop(self):
        """
        Boots up the webcam and continuously analyzes frames in a worker thread.
        """
        mp_face_detection = mp.solutions.face_detection
        face_detection = mp_face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.7,
        )
        cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            print("[ERROR] Failed to open webcam.")
            self.is_running = False
            face_detection.close()
            return

        self.last_seen_time = time.time()
        print("[AI PROCTOR] Security Camera Online. Monitoring started...")

        try:
            while self.is_running and cap.isOpened():
                success, image = cap.read()
                if not success:
                    print("[ERROR] Failed to read from webcam.")
                    break

                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                results = face_detection.process(image_rgb)

                face_count = 0
                if results.detections:
                    face_count = len(results.detections)

                    for detection in results.detections:
                        bbox = detection.location_data.relative_bounding_box
                        height, width, _ = image.shape
                        x1 = max(int(bbox.xmin * width), 0)
                        y1 = max(int(bbox.ymin * height), 0)
                        x2 = min(int((bbox.xmin + bbox.width) * width), width)
                        y2 = min(int((bbox.ymin + bbox.height) * height), height)
                        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)

                if face_count == 0:
                    if (
                        self.last_seen_time is not None
                        and time.time() - self.last_seen_time > 3.0
                    ):
                        print("WARNING: Student face not detected! Looking away?")
                        self.violation_strikes += 1
                        self.last_seen_time = time.time()
                else:
                    self.last_seen_time = time.time()

                if face_count > 1:
                    print(
                        f"CRITICAL VIOLATION: {face_count} faces detected in frame!"
                    )
                    self.violation_strikes += 1

                cv2.putText(
                    image,
                    f"Strikes: {self.violation_strikes}",
                    (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 0, 255),
                    2,
                )
                cv2.putText(
                    image,
                    f"Faces: {face_count}",
                    (20, 90),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 0, 0),
                    2,
                )

                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                with self.lock:
                    self.latest_frame = image_rgb
        finally:
            cap.release()
            face_detection.close()
            self.is_running = False

    def start_monitoring(self):
        """
        Launch the webcam processing loop in a background daemon thread.
        """
        if self.is_running:
            return

        self.is_running = True
        threading.Thread(target=self.run_camera_loop, daemon=True).start()

    def get_latest_frame_and_strikes(self):
        """
        Safely return the latest annotated RGB frame and current strike count.
        """
        with self.lock:
            frame = None if self.latest_frame is None else np.copy(self.latest_frame)
            strikes = self.violation_strikes
        return frame, strikes


if __name__ == "__main__":
    proctor = AIProctor()
    proctor.start_monitoring()
    while proctor.is_running:
        time.sleep(0.1)
