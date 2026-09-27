"""Embedded camera preview panel for the execution view."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
from qtpy.QtCore import QEvent, QThread, QTimer, Qt, Signal
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import (
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from dayu_widgets.check_box import MCheckBox
from dayu_widgets.combo_box import MComboBox
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from ui.video_playback import VideoPlayback
from ui.annotation_canvas import AnnotationCanvas
from ui.video_annotation_panel import VideoAnnotationPanel


FOV_OPTIONS = {0: "86°", 1: "78°", 2: "65°"}
EXPOSURE_OPTIONS = {
    0: "+0.0 EV", 3: "+0.3", 7: "+0.7", 10: "+1.0", 13: "+1.3",
    17: "+1.7", 20: "+2.0", 23: "+2.3", 27: "+2.7", 30: "+3.0",
    -30: "-3.0", -27: "-2.7", -23: "-2.3", -20: "-2.0",
    -17: "-1.7", -13: "-1.3", -10: "-1.0", -7: "-0.7", -3: "-0.3",
}
AI_SUB_MODE = {0: "标准", 1: "上半身", 2: "特写", 3: "无头", 4: "下半身", 5: "Butt"}
WDR_OPTIONS = {0: "关闭", 1: "DOL 2→1", 2: "Sensor"}


class _AspectRatioContainer(QWidget):
    """Keep the child label at the largest exact 16:9 size that fits."""

    def __init__(self, preview: QLabel, parent=None):
        super().__init__(parent)
        self._preview = preview
        self._preview.setParent(self)
        self._overlay = None

    def set_overlay(self, overlay: QWidget):
        self._overlay = overlay
        self._overlay.setParent(self)
        self._layout_children()

    def _layout_children(self):
        rect = self.contentsRect()
        unit = max(1, min(rect.width() // 16, rect.height() // 9))
        width = unit * 16
        height = unit * 9
        left = rect.x() + (rect.width() - width) // 2
        top = rect.y() + (rect.height() - height) // 2
        self._preview.setGeometry(left, top, width, height)
        if self._overlay is not None:
            self._overlay.move(
                left + width - self._overlay.width() - 8,
                top + 8,
            )
            self._overlay.raise_()

    def resizeEvent(self, event):
        self._layout_children()
        super().resizeEvent(event)


class EmbeddedCameraPanel(QFrame):
    """Compact camera preview shell that reuses the existing camera captures."""

    playback_layout_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._camera_type = "tinyse"
        self._thread: Optional[QThread] = None
        self._capture = None
        self._control = None
        self._record_path: Optional[str] = None
        self._preview_start_time: Optional[float] = None
        self._preview_active = False
        self._status_text = "Idle"
        self._replay_mode = False
        self._last_recording_path = None
        self._display_frame = None
        self._playback = VideoPlayback(self)

        self._build_ui()
        self._playback.opened.connect(self._on_playback_opened)
        self._playback.frame_ready.connect(self._on_playback_frame)
        self._playback.playing_changed.connect(
            lambda playing: self._play_button.setText("暂停" if playing else "播放")
        )
        self._playback.error.connect(self._on_playback_error)
        self._set_running(False)

    def _build_ui(self):
        self.setStyleSheet(
            "EmbeddedCameraPanel {"
            "  background-color: rgba(18, 18, 22, 0.92);"
            "  border: 1px solid rgba(90, 90, 95, 0.7);"
            "  border-radius: 8px;"
            "}"
            'EmbeddedCameraPanel[integrated="true"] {'
            "  background: transparent; border: none;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self._preview = AnnotationCanvas("未连接相机")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(320, 180)
        self._preview.setFocusPolicy(Qt.StrongFocus)
        self._preview.installEventFilter(self)
        self._preview.setStyleSheet(
            "QLabel { background-color: #111; color: #888; border: none; }"
            'QLabel[integrated="true"] { background-color: #0e141d; color: #768394; }'
        )
        self._preview_container = _AspectRatioContainer(self._preview)
        self._preview_container.setMinimumSize(320, 180)
        layout.addWidget(self._preview_container, 1)
        self._build_playback_controls(layout)

        self._btn_settings = MPushButton("⚙")
        self._btn_settings.setFixedSize(30, 28)
        self._btn_settings.setToolTip("摄像头设置")
        self._btn_settings.setStyleSheet(
            "font-size: 13pt; padding: 0; "
            "background-color: #3b3b3b; border: 1px solid #555; border-radius: 5px;"
        )
        self._menu = QMenu(self)
        self._menu.setMinimumWidth(340)
        self._build_settings_controls()
        self._menu.addSeparator()
        self._restart_action = self._menu.addAction("重新启动预览")
        self._restart_action.triggered.connect(self._restart_preview)
        self._record_action = self._menu.addAction("Record")
        self._record_action.triggered.connect(self._on_record)
        self._replay_action = self._menu.addAction("回放本次录像")
        self._replay_action.triggered.connect(lambda: self.open_recording(self._last_recording_path))
        self._open_action = self._menu.addAction("打开录像…")
        self._open_action.triggered.connect(self._choose_recording)
        self._menu.aboutToShow.connect(self._refresh_menu)
        self._btn_settings.setMenu(self._menu)
        self._preview_container.set_overlay(self._btn_settings)

    def _build_playback_controls(self, layout):
        self._playback_bar = QWidget()
        controls = QVBoxLayout(self._playback_bar)
        controls.setContentsMargins(4, 4, 4, 4)
        controls.setSpacing(4)
        row = QHBoxLayout()
        self._play_button = MPushButton("播放")
        self._play_button.clicked.connect(self._toggle_playback)
        self._previous_button = MPushButton("上一帧")
        self._previous_button.clicked.connect(lambda: self._playback.step(-1))
        self._next_button = MPushButton("下一帧")
        self._next_button.clicked.connect(lambda: self._playback.step(1))
        self._speed = MComboBox()
        for speed in (0.25, 0.5, 1.0):
            self._speed.addItem(f"{speed:g}×", speed)
        self._speed.setCurrentIndex(2)
        self._speed.currentIndexChanged.connect(lambda: self._playback.set_rate(self._speed.currentData()))
        for widget in (self._play_button, self._previous_button, self._next_button, self._speed):
            row.addWidget(widget)
        controls.addLayout(row)
        self._position = QSlider(Qt.Horizontal)
        self._position.sliderPressed.connect(self._playback.pause)
        self._position.valueChanged.connect(self._playback.seek)
        controls.addWidget(self._position)
        row = QHBoxLayout()
        self._playback_time = QLabel()
        self._playback_time.setWordWrap(True)
        row.addWidget(self._playback_time, 1)
        back = MPushButton("返回实时")
        back.clicked.connect(self._leave_playback)
        row.addWidget(back)
        controls.addLayout(row)
        self._playback_source = QLabel()
        self._playback_source.setWordWrap(True)
        controls.addWidget(self._playback_source)
        self._annotation_tools = VideoAnnotationPanel(self._playback, self._preview)
        self._annotation_tools.layout_changed.connect(self.playback_layout_changed.emit)
        self._annotation_tools.list.installEventFilter(self)
        controls.addWidget(self._annotation_tools)
        layout.addWidget(self._playback_bar)
        self._playback_bar.hide()

    def _choose_recording(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开录像", "", "AVI 录像 (*.avi)")
        if path:
            self.open_recording(path)

    def open_recording(self, path):
        if not path or (self._capture is not None and self._is_record_busy(self._capture)):
            return
        self._replay_mode = True
        self._annotation_tools.reset(path)
        self._display_frame = None
        self._preview.setText("正在打开录像…")
        self._playback_time.setText("正在读取…")
        self._playback_source.clear()
        self._set_playback_controls_enabled(False)
        self._speed.setCurrentIndex(2)
        self._playback_bar.show()
        self._preview.setFocus()
        self._refresh_menu()
        self.playback_layout_changed.emit()
        self._playback.open(path)

    def _set_playback_controls_enabled(self, enabled):
        for widget in (self._play_button, self._previous_button, self._next_button, self._speed, self._position):
            widget.setEnabled(enabled)

    def _on_playback_opened(self, info):
        self._set_playback_controls_enabled(True)
        self._position.blockSignals(True)
        self._position.setRange(0, info.frame_count - 1)
        self._position.setValue(0)
        self._position.blockSignals(False)
        self._playback_source.setText(
            f"{info.time_source} · {info.warning}" if info.warning else info.time_source
        )

    def _on_playback_frame(self, frame, index, timestamp):
        if not self._replay_mode:
            return
        self._display_frame = frame
        self._render_frame(frame)
        self._annotation_tools.on_frame(frame, index)
        self._position.blockSignals(True)
        self._position.setValue(index)
        self._position.blockSignals(False)
        info = self._playback.info
        self._playback_time.setText(
            f"第 {index + 1}/{info.frame_count} 帧  ·  {timestamp:.3f} / {info.times[-1]:.3f} s"
        )

    def _on_playback_error(self, message):
        self._annotation_tools.on_error()
        self._display_frame = None
        self._preview.setText(f"回放失败：{message}")
        self._playback_time.setText("画面读取失败")
        self._playback_source.setText(message)
        self._set_status(message)
        if self._playback.info is None:
            self._set_playback_controls_enabled(False)

    def _toggle_playback(self):
        if self._playback.playing:
            self._playback.pause()
        else:
            self._playback.play()

    def _leave_playback(self):
        self._annotation_tools.reset()
        self._playback.close()
        self._replay_mode = False
        self._display_frame = None
        self._playback_bar.hide()
        self._preview.setText("等待实时画面…" if self._preview_active else "未连接相机")
        self._refresh_menu()
        self.playback_layout_changed.emit()

    def playback_controls_height(self):
        return self._playback_bar.sizeHint().height() if self._replay_mode else 0

    def eventFilter(self, watched, event):
        if self._replay_mode and event.type() == QEvent.KeyPress and watched in (self._preview, self._annotation_tools.list):
            if event.key() == Qt.Key_Delete:
                self._annotation_tools.delete_selected()
                return True
            if event.key() == Qt.Key_Escape:
                self._annotation_tools.cancel()
                return True
        if watched is self._preview:
            if event.type() == QEvent.Resize and self._display_frame is not None:
                QTimer.singleShot(0, self._redraw_frame)
            if self._replay_mode and event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Left:
                    self._playback.step(-1)
                    return True
                if event.key() == Qt.Key_Right:
                    self._playback.step(1)
                    return True
                if event.key() == Qt.Key_Space:
                    self._toggle_playback()
                    return True
        return super().eventFilter(watched, event)

    def _redraw_frame(self):
        if self._display_frame is not None:
            self._render_frame(self._display_frame)

    def keyPressEvent(self, event):
        if self._replay_mode and event.key() == Qt.Key_Escape:
            self._annotation_tools.cancel()
            event.accept()
        elif self._replay_mode and event.key() == Qt.Key_Delete:
            self._annotation_tools.delete_selected()
            event.accept()
        else:
            super().keyPressEvent(event)

    def set_integrated_style(self, enabled: bool):
        """Blend the ground-test preview into the continuous workspace."""
        for widget in (self, self._preview):
            widget.setProperty("integrated", enabled)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _build_settings_controls(self):
        panel = QWidget(self._menu)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self._chk_mirror = MCheckBox("镜像")
        self._chk_mirror.stateChanged.connect(self._on_mirror)
        row.addWidget(self._chk_mirror)
        self._cmb_fov = MComboBox()
        for value, label in FOV_OPTIONS.items():
            self._cmb_fov.addItem(label, value)
        self._cmb_fov.currentIndexChanged.connect(self._on_fov_changed)
        row.addWidget(MLabel("视野:"))
        row.addWidget(self._cmb_fov)
        layout.addLayout(row)

        row = QHBoxLayout()
        self._cmb_ai = MComboBox()
        for value, label in sorted(AI_SUB_MODE.items()):
            self._cmb_ai.addItem(label, value)
        self._cmb_ai.setCurrentIndex(4)
        row.addWidget(MLabel("AI 追踪:"))
        row.addWidget(self._cmb_ai)
        self._btn_ai_go = MPushButton("激活")
        self._btn_ai_go.clicked.connect(self._on_ai_go)
        row.addWidget(self._btn_ai_go)
        self._btn_ai_off = MPushButton("关闭")
        self._btn_ai_off.clicked.connect(self._on_ai_off)
        row.addWidget(self._btn_ai_off)
        layout.addLayout(row)

        row = QHBoxLayout()
        self._chk_af = MCheckBox("自动对焦")
        self._chk_af.setChecked(True)
        self._chk_af.stateChanged.connect(self._on_af_changed)
        row.addWidget(self._chk_af)
        self._cmb_exp = MComboBox()
        for value, label in sorted(EXPOSURE_OPTIONS.items()):
            self._cmb_exp.addItem(label, value)
        self._cmb_exp.setCurrentIndex(self._cmb_exp.findData(0))
        self._cmb_exp.currentIndexChanged.connect(self._on_exp_changed)
        row.addWidget(MLabel("曝光:"))
        row.addWidget(self._cmb_exp)
        layout.addLayout(row)

        row = QHBoxLayout()
        self._cmb_flicker = MComboBox()
        self._cmb_flicker.addItem("60Hz", 0)
        self._cmb_flicker.addItem("50Hz", 1)
        self._cmb_flicker.currentIndexChanged.connect(self._on_flicker_changed)
        row.addWidget(MLabel("抗频闪:"))
        row.addWidget(self._cmb_flicker)
        self._cmb_wdr = MComboBox()
        for value, label in WDR_OPTIONS.items():
            self._cmb_wdr.addItem(label, value)
        self._cmb_wdr.currentIndexChanged.connect(self._on_wdr_changed)
        row.addWidget(MLabel("HDR:"))
        row.addWidget(self._cmb_wdr)
        layout.addLayout(row)

        self._controls_action = QWidgetAction(self._menu)
        self._controls_action.setDefaultWidget(panel)
        self._menu.addAction(self._controls_action)

    def set_camera_type(self, camera_type: str):
        if camera_type == self._camera_type:
            return
        was_running = self._preview_active
        self.shutdown()
        self._camera_type = camera_type
        self._preview.setText("未连接相机")
        self._set_status("Idle")
        if was_running:
            self.start_preview()

    def start_preview(self):
        if self._replay_mode:
            return
        self._display_frame = None
        self._preview.setText("正在连接相机")
        if self._thread is not None:
            if hasattr(self._capture, "set_preview_enabled"):
                self._capture.set_preview_enabled(True)
            self._preview_active = True
            self._preview_start_time = time.perf_counter()
            self._set_running(True)
            return

        if self._camera_type == "tinyse":
            self._ensure_control()
        try:
            capture = self._create_capture()
        except Exception as exc:
            self._on_error(str(exc))
            return

        thread = QThread(self)
        capture.moveToThread(thread)
        capture.frame_ready.connect(self._on_frame)
        capture.recording_finished.connect(self._on_recording_finished)
        capture.error.connect(self._on_error)
        thread.started.connect(capture.start)
        thread.finished.connect(capture.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._capture = capture
        if hasattr(capture, "set_mirror"):
            capture.set_mirror(self._chk_mirror.isChecked())
        self._preview_active = True
        self._preview_start_time = time.perf_counter()
        thread.start()
        self._set_running(True)

    def stop_preview(self):
        if self._replay_mode:
            self._leave_playback()
        self._display_frame = None
        capture = self._capture
        if capture is not None:
            if self._is_recording(capture):
                self._stop_record(capture)
            if hasattr(capture, "set_preview_enabled"):
                capture.set_preview_enabled(False)
        self._preview_active = False
        self._preview_start_time = None
        self._set_running(False)
        self._set_status("Idle")
        self._preview.setText("已停止")

    def _restart_preview(self):
        self.shutdown()
        self.start_preview()

    def shutdown(self):
        if self._replay_mode:
            self._leave_playback()
        self._playback.shutdown()
        self._display_frame = None
        capture = self._capture
        thread = self._thread
        if capture is not None:
            if self._is_record_busy(capture):
                self._stop_record(capture, wait=True)
            capture.stop()
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        self._thread = None
        self._capture = None
        self._preview_active = False
        self._preview_start_time = None
        self._record_path = None
        self._release_control()
        self._set_running(False)

    def _create_capture(self):
        if self._camera_type == "tinyse":
            from camera.tinyse_camera import TinySeCameraCapture

            return TinySeCameraCapture()
        if self._camera_type == "logi":
            from camera.logi_camera import CAMERA_INDEX, CameraCapture

            capture = CameraCapture()
            if not capture.open(CAMERA_INDEX):
                raise RuntimeError("无法打开 MX Brio，请检查连接。")
            return capture
        raise RuntimeError("基础预览暂未嵌入，请选择 MX Brio 或 Tiny SE。")

    def _on_frame(self, frame: np.ndarray):
        if not self._preview_active or self._replay_mode:
            return
        self._display_frame = frame
        self._render_frame(frame)
        self._preview_start_time = None

    def _render_frame(self, frame: np.ndarray):
        import cv2

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        target = self._preview.size()
        scale = min(target.width() / w, target.height() / h)
        disp_w = max(1, int(w * scale))
        disp_h = max(1, int(h * scale))
        if disp_w != w or disp_h != h:
            rgb = cv2.resize(rgb, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
        bytes_per_line = rgb.strides[0]
        image = QImage(
            rgb.data,
            rgb.shape[1],
            rgb.shape[0],
            bytes_per_line,
            QImage.Format_RGB888,
        ).copy()
        self._preview.setPixmap(QPixmap.fromImage(image))

    def _on_record(self):
        capture = self._capture
        if capture is None or self._replay_mode:
            return
        if self._is_record_busy(capture) and not self._is_recording(capture):
            return
        if not self._is_recording(capture):
            path = capture.start_record()
            if path:
                self._record_path = path
                self._last_recording_path = None
        else:
            self._stop_record(capture)
        self._refresh_menu()

    def _on_recording_finished(self, path: str):
        self._record_path = None
        if Path(path).suffix.lower() == ".avi":
            self._last_recording_path = path
        self._set_status(f"Saved: {path}")
        self._refresh_menu()

    def _on_error(self, message: str):
        self._set_status(f"Error: {message}")
        self.shutdown()
        self._preview.setText(f"相机错误：{message}")

    def _apply_control_settings(self, control):
        control.set_fov(int(self._cmb_fov.currentData() or 0))
        control.set_auto_focus(self._chk_af.isChecked())
        control.set_exposure_compensation(int(self._cmb_exp.currentData() or 0))
        control.set_anti_flicker(int(self._cmb_flicker.currentData() or 0))
        control.set_wdr(int(self._cmb_wdr.currentData() or 0))
        control.set_ai_off()

    def _ensure_control(self, apply_settings: bool = True) -> bool:
        if self._control is not None:
            if apply_settings:
                self._apply_control_settings(self._control)
            return True
        try:
            from camera.tinyse_camera import TinySeCameraControl

            control = TinySeCameraControl(0)
            if not control.init():
                control.close()
                self._set_status("SDK 控制不可用: 未检测到 Tiny SE")
                return False
            self._control = control
            if apply_settings:
                self._apply_control_settings(control)
            return True
        except Exception as exc:
            self._control = None
            self._set_status(f"SDK 控制不可用: {exc}")
            return False

    def _release_control(self):
        control = self._control
        self._control = None
        if control is not None:
            control.close()

    def _report_control_result(self, action: str, result: int):
        if result < 0:
            self._set_status(f"{action}失败，返回码: {result}")

    def _set_status(self, text: str):
        self._status_text = text
        tooltip = "摄像头设置"
        if text != "Idle":
            tooltip = f"{tooltip}\n{text}"
        self._btn_settings.setToolTip(tooltip)

    def _on_mirror(self, _state: int):
        if self._capture is not None and hasattr(self._capture, "set_mirror"):
            self._capture.set_mirror(self._chk_mirror.isChecked())

    def _on_fov_changed(self, _index: int):
        if self._control is not None:
            self._control.set_fov(int(self._cmb_fov.currentData()))

    def _on_ai_go(self):
        if self._ensure_control(apply_settings=False):
            result = self._control.set_ai_mode(int(self._cmb_ai.currentData()))
            self._report_control_result("AI 追踪", result)

    def _on_ai_off(self):
        if self._ensure_control(apply_settings=False):
            self._report_control_result("关闭 AI 追踪", self._control.set_ai_off())

    def _on_af_changed(self, _state: int):
        if self._control is not None:
            self._control.set_auto_focus(self._chk_af.isChecked())

    def _on_exp_changed(self, _index: int):
        if self._control is not None:
            self._control.set_exposure_compensation(int(self._cmb_exp.currentData()))

    def _on_flicker_changed(self, _index: int):
        if self._control is not None:
            self._control.set_anti_flicker(int(self._cmb_flicker.currentData()))

    def _on_wdr_changed(self, _index: int):
        if self._control is not None:
            self._control.set_wdr(int(self._cmb_wdr.currentData()))

    def _refresh_menu(self):
        capture = self._capture
        running = self._preview_active and capture is not None
        self._controls_action.setEnabled(self._camera_type == "tinyse" and not self._replay_mode)
        busy = self._is_record_busy(capture) if capture is not None else False
        recording = self._is_recording(capture) if capture is not None else False
        self._record_action.setEnabled(running and not (busy and not recording) and not self._replay_mode)
        self._restart_action.setEnabled(not self._replay_mode)
        self._replay_action.setEnabled(not busy and self._last_recording_path is not None)
        self._open_action.setEnabled(not busy)
        if busy and not recording:
            self._record_action.setText("Saving...")
        elif recording:
            self._record_action.setText("Stop Recording")
        else:
            self._record_action.setText("Record")

    def _set_running(self, _running: bool):
        self._refresh_menu()

    def _is_recording(self, capture) -> bool:
        if hasattr(capture, "is_recording"):
            return bool(capture.is_recording)
        return bool(getattr(capture, "_recording", False))

    def _is_record_busy(self, capture) -> bool:
        if hasattr(capture, "is_record_busy"):
            return bool(capture.is_record_busy)
        return self._is_recording(capture)

    def _stop_record(self, capture, wait: bool = False):
        try:
            capture.stop_record(wait=wait)
        except TypeError:
            capture.stop_record()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
