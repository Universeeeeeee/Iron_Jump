"""Embedded camera preview panel for the execution view."""

from __future__ import annotations

import logging
import threading
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
        self._closing_control = None
        self._pending_preview_start = False
        self._control_stop_failed = False
        self._waiting_for_control = False
        self._auto_tracking = True
        self._tracking_requested = False
        self._sdk_tracking = False
        self._pose_subscription = None
        self._tracking_notice = ''
        self._record_path: Optional[str] = None
        self._preview_start_time: Optional[float] = None
        self._preview_active = False
        self._status_text = "Idle"
        self._replay_mode = False
        self._last_recording_path = None
        self._display_frame = None
        self._vision_enabled = False
        self._vision = None
        self._overlay_visible = False
        self._pending_frame = None
        self._frame_lock = threading.Lock()
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(33)
        self._preview_timer.timeout.connect(self._show_latest_frame)
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
        self._vision_label = QLabel()
        self._vision_label.setWordWrap(True)
        self._vision_label.setStyleSheet("color: #aeb7c5; padding: 4px; font-size: 10pt;")
        self._vision_label.hide()
        layout.addWidget(self._vision_label)
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
        self._show_pose_action = self._menu.addAction("显示关节点")
        self._show_pose_action.setCheckable(True)
        self._show_pose_action.setChecked(True)
        self._show_pose_action.setToolTip("仅控制画面标记，左右脚识别继续运行")
        self._show_pose_action.toggled.connect(self._on_pose_visibility_changed)
        self._restart_action = self._menu.addAction("重新启动预览")
        self._restart_action.triggered.connect(self._restart_preview)
        self._record_action = self._menu.addAction("开始录像")
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
        row.setSpacing(2)
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
        self._stop_vision()
        self._replay_mode = True
        self._vision_label.hide()
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
        self._vision_label.setVisible(self._vision_enabled or self._sdk_tracking)
        if self._preview_active:
            self._start_vision()
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

        self._chk_sdk_tracking = MCheckBox("SDK 全身跟随")
        self._chk_sdk_tracking.setToolTip("使用当前人体识别控制相机，固定最大视野；停止后内置 AI 保持关闭")
        self._chk_sdk_tracking.toggled.connect(self._on_sdk_tracking)
        layout.addWidget(self._chk_sdk_tracking)

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

    def set_vision_enabled(self, enabled: bool):
        self._stop_vision()
        self._vision_enabled = enabled
        self._vision_label.setVisible(enabled and not self._replay_mode)
        self._vision_label.setText("连接 Tiny SE 后显示人体识别")
        if self._preview_active:
            self._start_vision()

    def _start_vision(self):
        if not (self._vision_enabled or self._sdk_tracking) or self._vision is not None:
            return
        if self._camera_type != "tinyse":
            self._vision_label.setText("请选择 Tiny SE 使用左右脚校验")
            return
        from vision.live_walking import LiveWalkingVision
        self._vision = LiveWalkingVision()
        if self._sdk_tracking:
            self._connect_sdk_tracking()
        self._vision.start()

    def _stop_vision(self):
        self._disconnect_sdk_tracking()
        vision, self._vision = self._vision, None
        if vision is not None:
            vision.stop()
        self._vision_label.setText("人体识别已停止")

    def _connect_sdk_tracking(self):
        if self._control is None:
            return
        if self._pose_subscription is None:
            self._pose_subscription = self._control.begin_tracking()
        if self._vision is not None:
            self._vision.pose_updates.connect(self._pose_subscription)

    def _disconnect_sdk_tracking(self):
        if self._pose_subscription is None:
            return
        if self._vision is not None:
            self._vision.pose_updates.disconnect(self._pose_subscription)
        self._pose_subscription = None
        if self._control is not None:
            self._control.end_tracking()

    def _on_sdk_tracking(self, checked):
        self._sdk_tracking = checked
        self._tracking_notice = ''
        self._auto_tracking = False
        self._tracking_requested = False
        for widget in (self._cmb_ai, self._btn_ai_go, self._btn_ai_off, self._cmb_fov):
            widget.setEnabled(not checked)
        if checked:
            self._cmb_fov.blockSignals(True)
            self._cmb_fov.setCurrentIndex(self._cmb_fov.findData(0))
            self._cmb_fov.blockSignals(False)
            if self._preview_active and self._ensure_control(apply_settings=False):
                self._start_vision()
                self._connect_sdk_tracking()
        else:
            self._disconnect_sdk_tracking()
            if not self._vision_enabled:
                self._stop_vision()

    def _submit_vision_frame(self, frame, timing):
        vision = self._vision
        if vision is not None and not self._replay_mode:
            vision.submit_camera_frame(frame, timing)

    def on_walking_snapshot(self, snapshot):
        if self._vision is not None and not self._replay_mode:
            self._vision.submit_walking_snapshot(snapshot)

    def set_camera_type(self, camera_type: str):
        if camera_type == self._camera_type:
            return
        was_running = self._preview_active or self._waiting_for_control or self._pending_preview_start
        self.shutdown()
        self._camera_type = camera_type
        self._preview.setText("未连接相机")
        self._set_status("Idle")
        if was_running:
            self.start_preview()

    def start_preview(self):
        if self._replay_mode or self._waiting_for_control:
            return
        if self._closing_control is not None:
            self._pending_preview_start = True
            self._set_status('正在等待上一相机控制进程停止')
            return
        if self._control_stop_failed:
            self._set_status('SDK 停止未确认，请检查相机后重新启动预览')
            return
        self._display_frame = None
        self._preview.setText("正在连接相机")
        if self._thread is not None:
            if hasattr(self._capture, "set_preview_enabled"):
                self._capture.set_preview_enabled(True)
            self._preview_active = True
            self._preview_start_time = time.perf_counter()
            self._preview_timer.start()
            self._start_vision()
            self._set_running(True)
            return

        if self._camera_type == "tinyse":
            self._waiting_for_control = True
            if not self._ensure_control():
                self._on_control_error("无法建立控制连接，请重新启动预览")
            return
        self._start_capture()

    def _on_control_idle(self):
        if self.sender() is self._control and self._waiting_for_control:
            self._waiting_for_control = False
            self._start_capture()

    def _start_capture(self):
        # Tiny SE control discovery and initial settings must finish before
        # DirectShow opens the camera. Waiting is asynchronous in start_preview.
        try:
            capture = self._create_capture()
        except Exception as exc:
            self._on_error(str(exc))
            return

        thread = QThread(self)
        capture.moveToThread(thread)
        capture.frame_ready.connect(self._queue_preview_frame, Qt.DirectConnection)
        if hasattr(capture, "analysis_frame_timed_ready"):
            capture.analysis_frame_timed_ready.connect(self._submit_vision_frame, Qt.DirectConnection)
        capture.recording_finished.connect(self._on_recording_finished)
        capture.error.connect(self._on_error)
        thread.started.connect(capture.start)
        thread.finished.connect(capture.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._capture = capture
        self._start_vision()
        if hasattr(capture, "set_mirror"):
            capture.set_mirror(self._chk_mirror.isChecked())
        self._preview_active = True
        self._preview_start_time = time.perf_counter()
        self._preview_timer.start()
        thread.start()
        self._set_running(True)

    def stop_preview(self):
        self._pending_preview_start = False
        if self._waiting_for_control:
            self._waiting_for_control = False
            self._release_control()
        self._stop_vision()
        self._preview_active = False
        self._preview_timer.stop()
        with self._frame_lock:
            self._pending_frame = None
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
        if self._closing_control is None:
            self._control_stop_failed = False  # Explicit retry after checking the camera.
        self.start_preview()

    def shutdown(self):
        self._pending_preview_start = False
        self._waiting_for_control = False
        self._stop_vision()
        self._preview_active = False
        self._preview_timer.stop()
        with self._frame_lock:
            self._pending_frame = None
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

    def _queue_preview_frame(self, frame: np.ndarray):
        # Runs on the capture thread: retain one frame and never touch widgets.
        with self._frame_lock:
            if self._preview_active and not self._replay_mode:
                self._pending_frame = frame

    def _show_latest_frame(self):
        if self._vision is not None and not self._replay_mode:
            from vision.live_walking import walking_check_text
            pose, status, check = self._vision.display_state()
            if (pose is not None and self._preview_active and self._auto_tracking
                    and not self._tracking_requested and not self._sdk_tracking):
                self._on_ai_go()
            check_text = walking_check_text(check)
            self._vision_label.setText(status + ("\n" + check_text if check_text else ""))
            if self._sdk_tracking and self._tracking_notice:
                self._vision_label.setText(self._vision_label.text() + '\n' + self._tracking_notice)
            if pose is None and self._overlay_visible and self._display_frame is not None:
                self._render_frame(self._display_frame)
        with self._frame_lock:
            frame = self._pending_frame
            self._pending_frame = None
        if frame is not None:
            self._on_frame(frame)

    def _on_frame(self, frame: np.ndarray):
        if not self._preview_active or self._replay_mode:
            return
        self._display_frame = frame
        self._render_frame(frame)
        self._preview_start_time = None

    def _render_frame(self, frame: np.ndarray):
        import cv2

        self._overlay_visible = False
        if self._vision is not None and not self._replay_mode and self._show_pose_action.isChecked():
            from vision.pose_overlay import draw_pose_overlay
            pose, _, _ = self._vision.display_state()
            if pose is not None:
                frame = draw_pose_overlay(frame.copy(), pose, mirrored=self._chk_mirror.isChecked())
                self._overlay_visible = True
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
        logging.getLogger(__name__).error("Camera error: %s", message)
        self.shutdown()
        notice = "相机预览不可用，请检查连接后重试"
        self._set_status(notice)
        self._preview.setText(notice)

    def _apply_control_settings(self, control):
        control.request('set_fov', int(self._cmb_fov.currentData() or 0))
        control.request('set_auto_focus', self._chk_af.isChecked())
        control.request('set_exposure_compensation', int(self._cmb_exp.currentData() or 0))
        control.request('set_anti_flicker', int(self._cmb_flicker.currentData() or 0))
        control.request('set_wdr', int(self._cmb_wdr.currentData() or 0))
        if self._sdk_tracking and self._pose_subscription is None:
            self._pose_subscription = control.begin_tracking()

    def _ensure_control(self, apply_settings: bool = True) -> bool:
        if self._closing_control is not None or self._control_stop_failed:
            return False
        if self._control is not None:
            if apply_settings:
                self._apply_control_settings(self._control)
            return True
        try:
            from camera.control_service import CameraControlService

            control = CameraControlService(self)
            control.completed.connect(self._report_control_result)
            control.failed.connect(self._on_control_error)
            control.idle.connect(self._on_control_idle)
            if hasattr(control, 'tracking_event'):
                control.tracking_event.connect(self._on_tracking_event)
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
        self._tracking_requested = False
        if control is not None:
            if hasattr(control, 'closed'):
                self._closing_control = control
                control.closed.connect(self._on_control_closed)
                control.closed.connect(control.deleteLater)
            control.close()
            if not hasattr(control, 'closed'):
                control.deleteLater()

    def _on_control_closed(self):
        control = self.sender()
        if control is not self._closing_control:
            return
        self._closing_control = None
        if not getattr(control, '_stop_confirmed', True):
            self._control_stop_failed = True
        restart, self._pending_preview_start = self._pending_preview_start, False
        if restart and not self._control_stop_failed:
            self.start_preview()

    def _on_control_error(self, message):
        sender = self.sender()
        if sender is not None and sender is not self._control:
            if sender is self._closing_control:
                self._control_stop_failed = True
                self._pending_preview_start = False
                self._set_status(f'相机停止失败：{message}')
            return
        if self._sdk_tracking:
            self._chk_sdk_tracking.setChecked(False)
        self._set_status(f"相机设置失败：{message}")
        if self._waiting_for_control:
            self._waiting_for_control = False
            self._release_control()
            self._preview.setText(f"相机连接失败：{message}")

    def _on_tracking_event(self, event):
        if self.sender() is not None and self.sender() is not self._control:
            return
        if not self._sdk_tracking or event.get('event') != 'tracking_decision':
            return
        framing = event.get('framing')
        if framing is None:
            self._tracking_notice = 'SDK 跟随已暂停，等待新鲜、可靠的全身目标'
        elif not framing['fits_with_margin']:
            self._tracking_notice = '人体占满画面，请调整距离，保持头脚入镜'
        elif not framing['points_with_margin']:
            self._tracking_notice = '请保持头脚完整入镜，并留出画面边缘余量'
        else:
            self._tracking_notice = ''

    def _report_control_result(self, action: str, result: int):
        if self.sender() is not None and self.sender() is not self._control:
            return
        if result < 0:
            logging.getLogger(__name__).warning("Camera control %s failed: %s", action, result)
            self._set_status("相机设置失败，请重试")
        elif action == 'set_ai_mode':
            self._set_status("跟随指令已发送，请确认相机是否转动")
        elif action == 'set_ai_off':
            self._set_status("已发送关闭跟随指令")
        elif action == 'tracking_start':
            self._set_status("SDK 全身跟随已启用，请保持全身入镜")
        elif action == 'tracking_stop':
            self._set_status("SDK 跟随已停止，内置 AI 保持关闭")

    def _set_status(self, text: str):
        self._status_text = text
        tooltip = "摄像头设置"
        if text != "Idle":
            tooltip = f"{tooltip}\n{text}"
        self._btn_settings.setToolTip(tooltip)

    def _on_pose_visibility_changed(self, _checked: bool):
        if self._display_frame is not None:
            self._render_frame(self._display_frame)

    def _on_mirror(self, _state: int):
        if self._capture is not None and hasattr(self._capture, "set_mirror"):
            self._capture.set_mirror(self._chk_mirror.isChecked())

    def _on_fov_changed(self, _index: int):
        if self._control is not None:
            self._control.request('set_fov', int(self._cmb_fov.currentData()))

    def _on_ai_go(self):
        if self._sdk_tracking:
            return
        if self._ensure_control(apply_settings=False):
            self._auto_tracking = True
            self._tracking_requested = True
            self._control.request('set_ai_mode', int(self._cmb_ai.currentData()))

    def _on_ai_off(self):
        if self._sdk_tracking:
            return
        self._auto_tracking = False
        self._tracking_requested = False
        if self._ensure_control(apply_settings=False):
            self._control.request('set_ai_off')

    def _on_af_changed(self, _state: int):
        if self._control is not None:
            self._control.request('set_auto_focus', self._chk_af.isChecked())

    def _on_exp_changed(self, _index: int):
        if self._control is not None:
            self._control.request('set_exposure_compensation', int(self._cmb_exp.currentData()))

    def _on_flicker_changed(self, _index: int):
        if self._control is not None:
            self._control.request('set_anti_flicker', int(self._cmb_flicker.currentData()))

    def _on_wdr_changed(self, _index: int):
        if self._control is not None:
            self._control.request('set_wdr', int(self._cmb_wdr.currentData()))

    def _refresh_menu(self):
        capture = self._capture
        running = self._preview_active and capture is not None
        self._controls_action.setEnabled(self._camera_type == "tinyse" and not self._replay_mode)
        self._chk_sdk_tracking.setEnabled(self._camera_type == "tinyse" and not self._replay_mode)
        busy = self._is_record_busy(capture) if capture is not None else False
        recording = self._is_recording(capture) if capture is not None else False
        self._record_action.setEnabled(running and not (busy and not recording) and not self._replay_mode)
        self._restart_action.setEnabled(not self._replay_mode)
        self._replay_action.setEnabled(not busy and self._last_recording_path is not None)
        self._open_action.setEnabled(not busy)
        if busy and not recording:
            self._record_action.setText("正在保存…")
        elif recording:
            self._record_action.setText("停止录像")
        else:
            self._record_action.setText("开始录像")

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
