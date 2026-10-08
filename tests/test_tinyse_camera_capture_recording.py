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
            capture._decode_preview_frame(*capture._pending_mjpg)

        self.assertEqual(capture.analysis_frame_ready.values, [(frame, 100.012)])
        emitted_frame, timing = capture.analysis_frame_timed_ready.values[0]
        self.assertIs(emitted_frame, frame)
        self.assertEqual(timing.frame_index, 7)
        self.assertEqual(timing.sample_time_s, 1.25)
        self.assertEqual(timing.callback_time_s, 100.0)
        self.assertEqual(timing.decoded_at_s, 100.012)


if __name__ == "__main__":
    unittest.main()


def test_stop_leaves_native_cleanup_on_capture_worker():
    from types import SimpleNamespace
    entered = threading.Event()
    release = threading.Event()
    closed_on = []

    class NativeCapture:
        def start(self):
            pass
        def stats(self):
            entered.set()
            assert release.wait(2)
            return SimpleNamespace(wall_fps=100)
        def stop(self):
            raise AssertionError('native stop must not race worker cleanup')
        def close(self):
            closed_on.append(threading.get_ident())

    capture = TinySeCameraCapture()
    capture._capture = NativeCapture()
    worker = threading.Thread(target=capture.start)
    worker.start()
    try:
        assert entered.wait(2)
        capture.stop()
        assert closed_on == []
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert closed_on == [worker.ident]
    assert capture._capture is None


def test_stop_during_native_start_does_not_resume_capture():
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class NativeCapture:
        def start(self):
            entered.set()
            assert release.wait(2)
        def stats(self):
            raise AssertionError('capture resumed after stop request')
        def close(self):
            closed.set()

    capture = TinySeCameraCapture()
    capture._capture = NativeCapture()
    capture.started = _Emitter()
    capture.error = _Emitter()
    worker = threading.Thread(target=capture.start)
    worker.start()
    try:
        assert entered.wait(2)
        capture.stop()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert closed.is_set()
    assert capture.started.values == []
    assert capture.error.values == []


def test_native_callback_retains_only_latest_compressed_frame_without_decoding():
    capture = TinySeCameraCapture(preview_fps=30)
    with patch.object(tinyse_camera.cv2, 'imdecode') as decode:
        for i in range(100):
            capture._on_mjpg_frame(b'jpeg', i, i / 20, 100 + i / 20)
        decode.assert_not_called()
    assert capture._pending_mjpg == (b'jpeg', 99, 4.95, 104.95)
    assert capture._preview_wake.is_set()


def test_slow_preview_decode_does_not_back_up_native_frames():
    from types import SimpleNamespace
    entered, release, latest = threading.Event(), threading.Event(), threading.Event()
    seen = []
    class NativeCapture:
        def start(self):
            pass
        def stats(self):
            return SimpleNamespace(wall_fps=100)
        def close(self):
            pass
    capture = TinySeCameraCapture(preview_fps=30)
    capture._capture = NativeCapture()
    def decode(data, index, sample, callback):
        seen.append((index, threading.get_ident()))
        if index == 0:
            entered.set()
            assert release.wait(2)
        else:
            latest.set()
    capture._decode_preview_frame = decode
    worker = threading.Thread(target=capture.start)
    worker.start()
    try:
        capture._on_mjpg_frame(b'jpeg', 0, 0, 100)
        assert entered.wait(1)
        for i in range(1, 101):
            capture._on_mjpg_frame(b'jpeg', i, i / 20, 100 + i / 20)
        release.set()
        assert latest.wait(1)
        assert seen == [(0, worker.ident), (100, worker.ident)]
    finally:
        release.set()
        capture.stop()
        worker.join(2)
        assert not worker.is_alive()


def test_mirror_switch_changes_delivered_preview_pixels_only():
    import cv2
    import numpy as np

    pixels = np.zeros((32, 64, 3), dtype=np.uint8)
    pixels[:, :20] = (20, 80, 230)
    pixels[:, 20:] = (200, 40, 10)
    ok, encoded = cv2.imencode('.jpg', pixels)
    assert ok
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    assert not np.array_equal(decoded, decoded[:, ::-1])
    for mirrored in (False, True):
        capture = TinySeCameraCapture()
        capture.set_mirror(mirrored)
        capture.analysis_frame_timed_ready = _Emitter()
        capture.analysis_frame_ready = _Emitter()
        capture.frame_ready = _Emitter()
        capture._decode_preview_frame(encoded.tobytes(), 7, 1.25, 100.0)
        analysis, timing = capture.analysis_frame_timed_ready.values[0]
        preview = capture.frame_ready.values[0][0]
        np.testing.assert_array_equal(analysis, decoded)
        np.testing.assert_array_equal(preview, decoded[:, ::-1] if mirrored else decoded)
        assert timing.sample_time_s == 1.25
        assert timing.callback_time_s == 100.0
