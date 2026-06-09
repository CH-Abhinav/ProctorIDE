import copy
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


def build_fake_cv2(frame_sequences):
    module = types.ModuleType("cv2")
    module.COLOR_BGR2RGB = 1
    module.FONT_HERSHEY_SIMPLEX = 0

    def fake_cvtColor(image, _code):
        return image

    def fake_rectangle(*_args, **_kwargs):
        return None

    def fake_putText(*_args, **_kwargs):
        return None

    class FakeVideoCapture:
        last_instance = None

        def __init__(self, _camera_index):
            self._frames = list(frame_sequences)
            self._read_index = 0
            self.released = False
            FakeVideoCapture.last_instance = self

        def isOpened(self):
            return not self.released

        def read(self):
            if self._read_index < len(self._frames):
                frame = self._frames[self._read_index]
                self._read_index += 1
                return True, frame
            return False, None

        def release(self):
            self.released = True

    module.VideoCapture = FakeVideoCapture
    module.cvtColor = fake_cvtColor
    module.rectangle = fake_rectangle
    module.putText = fake_putText
    return module


def build_fake_mediapipe(face_detections):
    module = types.ModuleType("mediapipe")
    face_detection_module = types.SimpleNamespace()

    class FakeFaceDetection:
        last_instance = None

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.closed = False
            FakeFaceDetection.last_instance = self

        def process(self, _image_rgb):
            return types.SimpleNamespace(detections=face_detections)

        def close(self):
            self.closed = True

    face_detection_module.FaceDetection = FakeFaceDetection
    module.solutions = types.SimpleNamespace(face_detection=face_detection_module)
    return module


def build_fake_numpy():
    module = types.ModuleType("numpy")
    module.copy = copy.deepcopy
    return module


def import_proctor_module(frame_sequences, face_detections):
    fake_cv2 = build_fake_cv2(frame_sequences)
    fake_mp = build_fake_mediapipe(face_detections)
    fake_np = build_fake_numpy()

    with patch.dict(
        sys.modules,
        {
            "cv2": fake_cv2,
            "mediapipe": fake_mp,
            "numpy": fake_np,
        },
    ):
        sys.modules.pop("proctor_ai", None)
        return importlib.import_module("proctor_ai")


def make_detection():
    bounding_box = types.SimpleNamespace(
        xmin=0.1,
        ymin=0.1,
        width=0.2,
        height=0.2,
    )
    location_data = types.SimpleNamespace(relative_bounding_box=bounding_box)
    return types.SimpleNamespace(location_data=location_data)


def make_frame(label):
    frame = types.SimpleNamespace(label=label, shape=(2, 2, 3))
    return frame


class TrackingLock:
    def __init__(self):
        self.enter_count = 0
        self.exit_count = 0

    def __enter__(self):
        self.enter_count += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exit_count += 1
        return False


class AIProctorTests(unittest.TestCase):
    def test_start_monitoring_spawns_daemon_thread(self):
        module = import_proctor_module(frame_sequences=[make_frame("unused")], face_detections=[])
        proctor = module.AIProctor()
        created_threads = []

        class FakeThread:
            def __init__(self, target, daemon):
                self.target = target
                self.daemon = daemon
                self.started = False
                created_threads.append(self)

            def start(self):
                self.started = True

        with patch.object(module.threading, "Thread", FakeThread):
            proctor.start_monitoring()

        self.assertTrue(proctor.is_running)
        self.assertEqual(len(created_threads), 1)
        self.assertTrue(created_threads[0].daemon)
        self.assertIs(created_threads[0].target.__self__, proctor)
        self.assertIs(
            created_threads[0].target.__func__,
            proctor.run_camera_loop.__func__,
        )
        self.assertTrue(created_threads[0].started)

    def test_run_camera_loop_increments_strikes_when_no_face_is_detected(self):
        frame = make_frame("zero-face")
        module = import_proctor_module(
            frame_sequences=[frame],
            face_detections=None,
        )
        proctor = module.AIProctor()
        tracking_lock = TrackingLock()
        proctor.lock = tracking_lock
        proctor.is_running = True

        with patch.object(module.time, "time", side_effect=[100.0, 104.5, 104.6]):
            proctor.run_camera_loop()

        self.assertEqual(proctor.violation_strikes, 1)
        self.assertFalse(proctor.is_running)
        self.assertTrue(module.cv2.VideoCapture.last_instance.released)
        self.assertTrue(module.mp.solutions.face_detection.FaceDetection.last_instance.closed)
        self.assertEqual(tracking_lock.enter_count, 1)
        self.assertEqual(tracking_lock.exit_count, 1)

    def test_run_camera_loop_leaves_strikes_unchanged_for_one_face(self):
        frame = make_frame("one-face")
        module = import_proctor_module(
            frame_sequences=[frame],
            face_detections=[make_detection()],
        )
        proctor = module.AIProctor()
        tracking_lock = TrackingLock()
        proctor.lock = tracking_lock
        proctor.is_running = True

        with patch.object(module.time, "time", side_effect=[100.0, 101.0]):
            proctor.run_camera_loop()

        latest_frame, strikes = proctor.get_latest_frame_and_strikes()

        self.assertEqual(strikes, 0)
        self.assertEqual(proctor.violation_strikes, 0)
        self.assertIsNot(latest_frame, proctor.latest_frame)
        self.assertEqual(latest_frame, proctor.latest_frame)
        self.assertEqual(tracking_lock.enter_count, 2)
        self.assertEqual(tracking_lock.exit_count, 2)

    def test_run_camera_loop_increments_strikes_for_multiple_faces(self):
        frame = make_frame("multi-face")
        module = import_proctor_module(
            frame_sequences=[frame],
            face_detections=[make_detection(), make_detection()],
        )
        proctor = module.AIProctor()
        proctor.is_running = True

        with patch.object(module.time, "time", side_effect=[100.0, 100.5]):
            proctor.run_camera_loop()

        self.assertEqual(proctor.violation_strikes, 1)
        self.assertFalse(proctor.is_running)


if __name__ == "__main__":
    unittest.main()
