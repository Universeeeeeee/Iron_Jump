import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from vision.foot_reference import FootPoseSample
from vision.mediapipe_pose import MediaPipePoseAdapter, VisionUnavailableError


class _FakeLandmarker:
    def __init__(self, owner):
        self.owner = owner
        self.closed = False

    def detect_for_video(self, image, timestamp_ms):
        self.owner.detect_calls.append((image, timestamp_ms))
        point = SimpleNamespace(x=0.1, y=0.2, z=0.3, visibility=0.9, presence=0.8)
        return SimpleNamespace(pose_landmarks=[[point for _ in range(33)]])

    def close(self):
        self.closed = True


class _FakeMediaPipe:
    def __init__(self):
        self.options = None
        self.detect_calls = []
        self.landmarker = _FakeLandmarker(self)

        owner = self

        class PoseLandmarker:
            @staticmethod
            def create_from_options(options):
                owner.options = options
                return owner.landmarker

        class Image:
            def __init__(self, image_format, data):
                self.image_format = image_format
                self.data = data

        self.Image = Image
        self.ImageFormat = SimpleNamespace(SRGB="srgb")
        base_options = lambda **kwargs: SimpleNamespace(**kwargs)
        base_options.Delegate = SimpleNamespace(CPU="cpu", GPU="gpu")
        self.tasks = SimpleNamespace(
            BaseOptions=base_options,
            vision=SimpleNamespace(
                PoseLandmarker=PoseLandmarker,
                PoseLandmarkerOptions=lambda **kwargs: SimpleNamespace(**kwargs),
                RunningMode=SimpleNamespace(VIDEO="video"),
            ),
        )


class MediaPipePoseAdapterTests(unittest.TestCase):
    def _model_file(self, root: str) -> Path:
        path = Path(root) / "pose.task"
        path.write_bytes(b"fake")
        return path

    def test_open_rejects_missing_model(self):
        adapter = MediaPipePoseAdapter("missing.task", module_loader=_FakeMediaPipe)

        with self.assertRaisesRegex(VisionUnavailableError, "model file"):
            adapter.open()

    def test_open_uses_video_single_pose_without_segmentation(self):
        with tempfile.TemporaryDirectory() as root:
            fake = _FakeMediaPipe()
            adapter = MediaPipePoseAdapter(
                self._model_file(root), module_loader=lambda: fake
            )

            adapter.open()

            self.assertEqual(fake.options.running_mode, "video")
            self.assertEqual(fake.options.num_poses, 1)
            self.assertFalse(fake.options.output_segmentation_masks)
            self.assertEqual(fake.options.base_options.delegate, "cpu")

    def test_infer_converts_bgr_to_rgb_and_normalizes_required_landmarks(self):
        with tempfile.TemporaryDirectory() as root:
            fake = _FakeMediaPipe()
            adapter = MediaPipePoseAdapter(
                self._model_file(root), module_loader=lambda: fake
            )
            adapter.open()
            frame = np.array([[[1, 2, 3]]], dtype=np.uint8)

            sample = adapter.infer_bgr(frame, 123)

            self.assertIsInstance(sample, FootPoseSample)
            image, timestamp_ms = fake.detect_calls[0]
            self.assertEqual(timestamp_ms, 123)
            self.assertEqual(image.data.tolist(), [[[3, 2, 1]]])
            self.assertEqual(sample.left_hip.presence, 0.8)

    def test_infer_rejects_non_increasing_video_timestamp(self):
        with tempfile.TemporaryDirectory() as root:
            adapter = MediaPipePoseAdapter(
                self._model_file(root), module_loader=_FakeMediaPipe
            )
            adapter.open()
            frame = np.zeros((1, 1, 3), dtype=np.uint8)
            adapter.infer_bgr(frame, 100)

            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                adapter.infer_bgr(frame, 100)

    def test_close_releases_landmarker_and_resets_timestamp(self):
        with tempfile.TemporaryDirectory() as root:
            fake = _FakeMediaPipe()
            adapter = MediaPipePoseAdapter(
                self._model_file(root), module_loader=lambda: fake
            )
            adapter.open()
            adapter.infer_bgr(np.zeros((1, 1, 3), dtype=np.uint8), 100)

            adapter.close()

            self.assertTrue(fake.landmarker.closed)
            self.assertIsNone(adapter.last_timestamp_ms)


if __name__ == "__main__":
    unittest.main()
