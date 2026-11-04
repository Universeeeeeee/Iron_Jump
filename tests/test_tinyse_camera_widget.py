"""Tiny SE camera widget lifecycle tests."""

from __future__ import annotations

import sys
import ctypes
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _install_camera_dependency_stubs() -> None:
    """Provide tiny import-time stubs when Qt/OpenCV are unavailable."""

    if not hasattr(ctypes, "WINFUNCTYPE"):
        ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE

    try:
        import cv2  # noqa: F401
    except ModuleNotFoundError:
        cv2 = types.ModuleType("cv2")
        cv2.COLOR_BGR2RGB = 0
        cv2.IMREAD_COLOR = 1
        cv2.INTER_AREA = 0
        cv2.VideoWriter_fourcc = lambda *args: 0
        cv2.cvtColor = lambda frame, _code: frame
        cv2.resize = lambda frame, _size, interpolation=None: frame
        cv2.imdecode = lambda _data, _flags: None
        sys.modules["cv2"] = cv2

    try:
        import numpy  # noqa: F401
    except ModuleNotFoundError:
        numpy = types.ModuleType("numpy")
        numpy.ndarray = object
        numpy.uint8 = object
        numpy.frombuffer = lambda data, dtype=None: data
        sys.modules["numpy"] = numpy

    try:
        from qtpy.QtCore import QObject, QThread, Qt, Signal  # noqa: F401
        from qtpy.QtGui import QImage, QPixmap  # noqa: F401
        from qtpy.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget  # noqa: F401
    except ModuleNotFoundError:
        qtpy = types.ModuleType("qtpy")
        qtcore = types.ModuleType("qtpy.QtCore")
        qtgui = types.ModuleType("qtpy.QtGui")
        qtwidgets = types.ModuleType("qtpy.QtWidgets")

        class _Signal:
            def connect(self, _slot):
                pass

            def emit(self, *args):
                pass

        class _QObject:
            def __init__(self, parent=None):
                self.parent = parent

            def moveToThread(self, _thread):
                pass

        class _QThread:
            def __init__(self, parent=None):
                self.parent = parent
                self.started = _Signal()
                self.finished = _Signal()

            def start(self):
                pass

            def quit(self):
                pass

            def wait(self, _timeout):
                return True

            def deleteLater(self):
                pass

        class _Qt:
            AlignCenter = 0

        class _QImage:
            Format_RGB888 = 0

            def __init__(self, *args, **kwargs):
                pass

            def copy(self):
                return self

        class _QPixmap:
            @staticmethod
            def fromImage(image):
                return image

        class _Widget:
            def __init__(self, *args, **kwargs):
                pass

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        class _MessageBox(_Widget):
            @staticmethod
            def information(*args, **kwargs):
                pass

            @staticmethod
            def warning(*args, **kwargs):
                pass

            @staticmethod
            def critical(*args, **kwargs):
                pass

        qtcore.QObject = _QObject
        qtcore.QThread = _QThread
        qtcore.Signal = lambda *args, **kwargs: _Signal()
        qtcore.Qt = _Qt
        qtgui.QImage = _QImage
        qtgui.QPixmap = _QPixmap
        qtwidgets.QHBoxLayout = _Widget
        qtwidgets.QLabel = _Widget
        qtwidgets.QMessageBox = _MessageBox
        qtwidgets.QVBoxLayout = _Widget
        qtwidgets.QWidget = _Widget
        for name in ("QApplication", "QCheckBox", "QComboBox", "QFrame", "QPushButton", "QToolButton"):
            setattr(qtwidgets, name, _Widget)
        sys.modules["qtpy"] = qtpy
        sys.modules["qtpy.QtCore"] = qtcore
        sys.modules["qtpy.QtGui"] = qtgui
        sys.modules["qtpy.QtWidgets"] = qtwidgets



_install_camera_dependency_stubs()

from camera.tinyse_camera import TinySeCameraControl, TinySeCameraWidget


class _FakeCapture:
    is_recording = False

    def __init__(self) -> None:
        self.preview_states: list[bool] = []
        self.stop_called = False
        self.stop_record_called = False
        self.stop_record_waits: list[bool] = []
        self._record_busy = False

    @property
    def is_record_busy(self) -> bool:
        return self.is_recording or self._record_busy

    def set_preview_enabled(self, enabled: bool) -> None:
        self.preview_states.append(enabled)

    def stop(self) -> None:
        self.stop_called = True

    def stop_record(self, wait: bool = False) -> bool:
        self.stop_record_called = True
        self.stop_record_waits.append(wait)
        self.is_recording = False
        self._record_busy = True
        return True


class _FakeThread:
    def __init__(self) -> None:
        self.quit_called = False
        self.wait_called = False

    def quit(self) -> None:
        self.quit_called = True

    def wait(self, _timeout: int) -> bool:
        self.wait_called = True
        return True


class _FakeCombo:
    def __init__(self, value: int) -> None:
        self._value = value

    def currentData(self) -> int:
        return self._value


class _FakeControl:
    def __init__(self, ret: int = 0) -> None:
        self.ret = ret
        self.ai_modes: list[int] = []
        self.ai_off_calls = 0
        self.calls: list[tuple[str, object]] = []

    def set_ai_mode(self, mode: int) -> int:
        self.ai_modes.append(mode)
        return self.ret

    def set_ai_off(self) -> int:
        self.ai_off_calls += 1
        return self.ret

    def set_fov(self, value: int) -> int:
        self.calls.append(("set_fov", value))
        return self.ret

    def set_auto_focus(self, value: bool) -> int:
        self.calls.append(("set_auto_focus", value))
        return self.ret

    def set_exposure_compensation(self, value: int) -> int:
        self.calls.append(("set_exposure_compensation", value))
        return self.ret

    def set_anti_flicker(self, value: int) -> int:
        self.calls.append(("set_anti_flicker", value))
        return self.ret

    def set_wdr(self, value: int) -> int:
        self.calls.append(("set_wdr", value))
        return self.ret


class _FakeControlDll:
    def __init__(self) -> None:
        self.close_calls = 0

    def obsbot_close(self) -> None:
        self.close_calls += 1


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.enabled = True

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class TinySeCameraWidgetLifecycleTest(unittest.TestCase):
    def test_stop_preview_keeps_capture_thread_alive_for_fast_restart(self):
        capture = _FakeCapture()
        thread = _FakeThread()
        running_states: list[bool] = []
        widget = SimpleNamespace(
            _capture=capture,
            _thread=thread,
            _preview_start_time=1.0,
            _preview_active=True,
            _set_running=lambda running: running_states.append(running),
        )

        TinySeCameraWidget._on_stop(widget)

        self.assertEqual(capture.preview_states, [False])
        self.assertFalse(capture.stop_called)
        self.assertFalse(thread.quit_called)
        self.assertIs(widget._capture, capture)
        self.assertIs(widget._thread, thread)
        self.assertFalse(widget._preview_active)
        self.assertEqual(running_states, [False])

    def test_start_preview_reuses_existing_capture_thread(self):
        capture = _FakeCapture()
        thread = _FakeThread()
        running_states: list[bool] = []
        widget = SimpleNamespace(
            _capture=capture,
            _thread=thread,
            _preview_start_time=None,
            _preview_active=False,
            _set_running=lambda running: running_states.append(running),
        )

        TinySeCameraWidget._on_start(widget)

        self.assertEqual(capture.preview_states, [True])
        self.assertIsNotNone(widget._preview_start_time)
        self.assertTrue(widget._preview_active)
        self.assertEqual(running_states, [True])

    def test_ai_go_initializes_control_without_preview(self):
        control = _FakeControl()
        ensure_calls: list[bool] = []
        reports: list[tuple[str, int]] = []
        widget = SimpleNamespace(
            _control=None,
            _cmb_ai=_FakeCombo(4),
            _report_control_result=lambda action, ret: reports.append((action, ret)),
        )

        def ensure_control(apply_settings: bool = True) -> bool:
            ensure_calls.append(apply_settings)
            widget._control = control
            return True

        widget._ensure_control = ensure_control
        widget._ctl = lambda: widget._control

        TinySeCameraWidget._on_ai_go(widget)

        self.assertEqual(ensure_calls, [False])
        self.assertEqual(control.ai_modes, [4])
        self.assertEqual(reports, [("AI 追踪", 0)])

    def test_ai_off_initializes_control_and_reports_failure(self):
        control = _FakeControl(ret=-3)
        ensure_calls: list[bool] = []
        reports: list[tuple[str, int]] = []
        widget = SimpleNamespace(
            _control=None,
            _report_control_result=lambda action, ret: reports.append((action, ret)),
        )

        def ensure_control(apply_settings: bool = True) -> bool:
            ensure_calls.append(apply_settings)
            widget._control = control
            return True

        widget._ensure_control = ensure_control
        widget._ctl = lambda: widget._control

        TinySeCameraWidget._on_ai_off(widget)

        self.assertEqual(ensure_calls, [False])
        self.assertEqual(control.ai_off_calls, 1)
        self.assertEqual(reports, [("关闭 AI 追踪", -3)])

    def test_default_control_settings_turn_ai_tracking_off(self):
        control = _FakeControl()
        widget = SimpleNamespace(
            _cmb_fov=_FakeCombo(0),
            _chk_af=SimpleNamespace(isChecked=lambda: True),
            _cmb_exp=_FakeCombo(0),
            _cmb_flicker=_FakeCombo(0),
            _cmb_wdr=_FakeCombo(0),
        )

        TinySeCameraWidget._apply_control_settings(widget, control)

        self.assertEqual(control.calls, [
            ("set_fov", 0),
            ("set_auto_focus", True),
            ("set_exposure_compensation", 0),
            ("set_anti_flicker", 0),
            ("set_wdr", 0),
        ])
        self.assertEqual(control.ai_modes, [])
        self.assertEqual(control.ai_off_calls, 1)

    def test_control_close_does_not_shutdown_process_sdk_singleton(self):
        control = object.__new__(TinySeCameraControl)
        dll = _FakeControlDll()
        control._dll = dll

        TinySeCameraControl.close(control)

        self.assertEqual(dll.close_calls, 0)
        self.assertIsNone(control._dll)

    def test_record_button_shows_saving_after_stop_record_starts(self):
        capture = _FakeCapture()
        capture.is_recording = True
        button = _FakeButton()
        widget = SimpleNamespace(
            _capture=capture,
            _btn_record=button,
            _record_path="camera/recordings/tinyse_test.mjpg",
        )

        TinySeCameraWidget._on_record(widget)

        self.assertEqual(capture.stop_record_waits, [False])
        self.assertEqual(button.text, "Saving...")
        self.assertFalse(button.enabled)

    def test_recording_finished_reenables_record_button_when_preview_active(self):
        button = _FakeButton()
        widget = SimpleNamespace(
            _record_path="camera/recordings/tinyse_test.mjpg",
            _btn_record=button,
            _preview_active=True,
        )

        with patch("camera.tinyse_camera.QMessageBox.information"):
            TinySeCameraWidget._on_recording_finished(widget, "camera/recordings/tinyse_test.avi")

        self.assertIsNone(widget._record_path)
        self.assertEqual(button.text, "Record")
        self.assertTrue(button.enabled)

    def test_shutdown_capture_waits_for_record_finalize_before_close(self):
        capture = _FakeCapture()
        capture.is_recording = True
        thread = _FakeThread()
        running_states: list[bool] = []
        widget = SimpleNamespace(
            _capture=capture,
            _thread=thread,
            _preview_active=True,
            _preview_start_time=1.0,
            _set_running=lambda running: running_states.append(running),
        )

        TinySeCameraWidget._shutdown_capture(widget)

        self.assertEqual(capture.stop_record_waits, [True])
        self.assertTrue(capture.stop_called)
        self.assertTrue(thread.quit_called)
        self.assertTrue(thread.wait_called)
        self.assertIsNone(widget._capture)
        self.assertIsNone(widget._thread)
        self.assertFalse(widget._preview_active)
        self.assertEqual(running_states, [False])


if __name__ == "__main__":
    unittest.main()
