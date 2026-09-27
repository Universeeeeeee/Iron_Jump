"""Tiny SE recording finalization tests."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_tinyse_camera_widget import _install_camera_dependency_stubs

_install_camera_dependency_stubs()

from camera import tinyse_camera
from camera.tinyse_camera import TinySeCameraCapture


class _Emitter:
    def __init__(self) -> None:
        self.values: list[tuple[object, ...]] = []

    def emit(self, *args) -> None:
        self.values.append(args)


class _SlowDShowCapture:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.stop_started = threading.Event()
        self.stop_finished = threading.Event()
        self.stop_calls = 0

    def stop_record(self):
        self.stop_calls += 1
        self.stop_started.set()
        if self.delay:
            time.sleep(self.delay)
        self.stop_finished.set()


class TinySeCameraCaptureRecordingTest(unittest.TestCase):
    def _recording_capture(
        self,
        dshow_capture: _SlowDShowCapture,
        mjpg_path: Path | None = None,
        csv_path: Path | None = None,
    ) -> TinySeCameraCapture:
        capture = TinySeCameraCapture()
        capture._capture = dshow_capture
        capture._recording = True
        capture._record_path = mjpg_path or Path("camera/recordings/tinyse_test.mjpg")
        capture._csv_path = csv_path or Path("camera/recordings/tinyse_test.csv")
        capture.recording_finished = _Emitter()
        capture.error = _Emitter()
        return capture

    def test_stop_record_returns_before_slow_finalize_finishes(self):
        dshow_capture = _SlowDShowCapture(delay=0.2)
        capture = self._recording_capture(dshow_capture)
        original_converter = tinyse_camera.mjpg_to_avi
        tinyse_camera.mjpg_to_avi = lambda mjpg, csv: mjpg.with_suffix(".avi")
        try:
            start = time.perf_counter()
            accepted = capture.stop_record()
            elapsed = time.perf_counter() - start

            self.assertTrue(accepted)
            finalize_thread = capture._record_finalize_thread
            self.assertIsNotNone(finalize_thread)
            self.assertLess(elapsed, 0.05)
            self.assertTrue(capture.is_record_busy)
            self.assertTrue(dshow_capture.stop_started.wait(1.0))
            self.assertTrue(dshow_capture.stop_finished.wait(1.0))
            finalize_thread.join(timeout=1.0)
            self.assertFalse(capture.is_record_busy)
            self.assertEqual(
                capture.recording_finished.values,
                [(str(Path("camera/recordings/tinyse_test.avi")),)],
            )
        finally:
            tinyse_camera.mjpg_to_avi = original_converter

    def test_stop_record_wait_true_finishes_before_returning(self):
        dshow_capture = _SlowDShowCapture(delay=0.01)
        capture = self._recording_capture(dshow_capture)
        original_converter = tinyse_camera.mjpg_to_avi
        tinyse_camera.mjpg_to_avi = lambda mjpg, csv: mjpg.with_suffix(".avi")
        try:
            accepted = capture.stop_record(wait=True)

            self.assertTrue(accepted)
            self.assertTrue(dshow_capture.stop_finished.is_set())
            self.assertFalse(capture.is_recording)
            self.assertFalse(capture.is_record_busy)
            self.assertIsNone(capture._record_path)
            self.assertIsNone(capture._csv_path)
            self.assertEqual(
                capture.recording_finished.values,
                [(str(Path("camera/recordings/tinyse_test.avi")),)],
            )
        finally:
            tinyse_camera.mjpg_to_avi = original_converter

    def test_finalize_does_not_publish_incomplete_recording_when_conversion_fails(self):
        dshow_capture = _SlowDShowCapture()
        capture = self._recording_capture(dshow_capture)
        original_converter = tinyse_camera.mjpg_to_avi

        def fail_conversion(_mjpg, _csv):
            raise RuntimeError("decode failed")

        tinyse_camera.mjpg_to_avi = fail_conversion
        try:
            accepted = capture.stop_record(wait=True)

            self.assertTrue(accepted)
            self.assertEqual(len(capture.error.values), 1)
            self.assertIn("MJPEG", capture.error.values[0][0])
            self.assertEqual(capture.recording_finished.values, [])
            self.assertFalse(capture.is_record_busy)
        finally:
            tinyse_camera.mjpg_to_avi = original_converter

    def test_completion_observes_finished_saving_state(self):
        capture = self._recording_capture(_SlowDShowCapture())
        observed = []
        capture.recording_finished.emit = lambda path: observed.append(capture.is_record_busy)
        with patch.object(tinyse_camera, "mjpg_to_avi", return_value=Path("clip.avi")):
            capture.stop_record(wait=True)
        self.assertEqual(observed, [False])

    def test_preserve_raw_does_not_convert_or_publish_avi(self):
        capture = self._recording_capture(_SlowDShowCapture())
        capture._record_preserve_raw = True
        with patch.object(tinyse_camera, "mjpg_to_avi") as convert:
            capture.stop_record(wait=True)
            convert.assert_not_called()
        self.assertEqual(capture.recording_finished.values, [])
        self.assertFalse(capture.is_record_busy)

    def test_analysis_frame_timing_preserves_sample_callback_and_decode_times(self):
        capture = TinySeCameraCapture(preview_fps=30)
        capture._mirror = False
        capture.analysis_frame_ready = _Emitter()
        capture.analysis_frame_timed_ready = _Emitter()
        capture.frame_ready = _Emitter()
        frame = object()

        with (
            patch.object(tinyse_camera.time, "perf_counter", return_value=100.012),
            patch.object(tinyse_camera.cv2, "imdecode", return_value=frame),
        ):
            capture._on_mjpg_frame(b"jpeg", 7, 1.25, 100.0)

        self.assertEqual(capture.analysis_frame_ready.values, [(frame, 100.012)])
        emitted_frame, timing = capture.analysis_frame_timed_ready.values[0]
        self.assertIs(emitted_frame, frame)
        self.assertEqual(timing.frame_index, 7)
        self.assertEqual(timing.sample_time_s, 1.25)
        self.assertEqual(timing.callback_time_s, 100.0)
        self.assertEqual(timing.decoded_at_s, 100.012)


if __name__ == "__main__":
    unittest.main()
