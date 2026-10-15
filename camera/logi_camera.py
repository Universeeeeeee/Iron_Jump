"""
logi_camera.py — Logitech MX Brio 摄像头独立预览窗口

基于 dayu_widgets + qtpy + OpenCV MSMF 后端。
可用于步态分析系统提供实时视觉参考。

使用方式::

    python -m camera.logi_camera

设计目标:
- 独立运行，不与 ui/ 目录现有模块耦合
- 后期可导入主界面嵌入
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import threading

import cv2
import numpy as np
from qtpy.QtCore import QObject, QThread, Signal, Qt
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from dayu_widgets.qt import application
from dayu_widgets import dayu_theme

# ──────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────

CAMERA_INDEX = 1              # MX Brio 实测索引
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
TARGET_FPS = 60
PREVIEW_WIDTH = 960           # 界面预览区缩放（1080p 的一半）
PREVIEW_HEIGHT = 540
RECORD_FOURCC = "MJPG"
RECORD_DIR = "recordings"

# ──────────────────────────────────────────────────────────────────────
# CameraCapture — 后台采集线程
# ──────────────────────────────────────────────────────────────────────


class CameraCapture(QObject):
    """运行在 QThread 中的摄像头采集控制器。

    Signals
    -------
    frame_ready(np.ndarray)
        新帧到达（BGR 格式）
    stats_updated(fps: float, record_seconds: float)
        实时帧率 / 录制时长
    recording_finished(path: str)
        录制文件已保存
    error(msg: str)
        不可恢复的错误
    """

    frame_ready = Signal(np.ndarray)
    analysis_frame_ready = Signal(object, float)
    stats_updated = Signal(float, float)
    recording_finished = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap: cv2.VideoCapture | None = None
        self._writer: cv2.VideoWriter | None = None
        self._running = False
        self._recording = False
        self._record_filepath: str | None = None
        self._record_start: float = 0.0
        self._fps_timer = _FpsCounter(window=30)
        self._lock = threading.Lock()

    # ── 公开接口 ──────────────────────────────────────────────────────

    def open(self, index: int = CAMERA_INDEX) -> bool:
        """打开摄像头，返回是否成功。"""
        cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
        if not cap.isOpened():
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
        self._cap = cap
        return True

    def start(self):
        """在 QThread.start() 后由 QThread 内部调用。"""
        self._running = True
        self._loop()

    def stop(self):
        """终止循环，释放资源。"""
        self._running = False

    def start_record(self) -> str | None:
        """开始录制，返回文件路径；如果已录制则返回 None。"""
        if self._cap is None:
            return None
        with self._lock:
            if self._recording:
                return None
            out_dir = Path(__file__).resolve().parent / RECORD_DIR
            out_dir.mkdir(exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = str(out_dir / f"mx_brio_{timestamp}.avi")
            fourcc = cv2.VideoWriter_fourcc(*RECORD_FOURCC)
            fil = self._fps_timer.fps()
            record_fps = fil if fil > 0 else TARGET_FPS
            w = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            h = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            writer = cv2.VideoWriter(path, fourcc, record_fps, (int(w), int(h)))
            if not writer.isOpened():
                self.error.emit(f"录像文件创建失败: {path}")
                return None
            self._writer = writer
            self._recording = True
            self._record_filepath = path
            self._record_start = time.perf_counter()
        return path

    def stop_record(self):
        """停止录制并关闭录像文件。"""
        path = None
        with self._lock:
            self._recording = False
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            if self._record_filepath is not None:
                path = self._record_filepath
                self._record_filepath = None
        if path is not None:
            self.recording_finished.emit(path)

    # ── 内部循环 ──────────────────────────────────────────────────────

    def _loop(self):
        """主采集循环（在采集线程中执行）。"""
        cap = self._cap
        if cap is None:
            self.error.emit("摄像头未打开")
            self._running = False
            return

        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    self.error.emit("无法读取视频帧")
                    break

                captured_at_s = time.perf_counter()
                self.analysis_frame_ready.emit(frame, captured_at_s)

                # 镜像处理（预览 + 录制都走同一帧）
                frame = cv2.flip(frame, 1)

                # 录制（锁只保护 writer 引用读取，写入在锁外）
                self._fps_timer.tick()
                with self._lock:
                    writer = self._writer if self._recording else None
                    record_sec = (
                        time.perf_counter() - self._record_start
                        if self._recording
                        else 0.0
                    )
                if writer is not None:
                    writer.write(frame)

                self.stats_updated.emit(self._fps_timer.fps(), record_sec)
                self.frame_ready.emit(frame)
        finally:
            self._cleanup()

    def _cleanup(self):
        self._running = False
        with self._lock:
            self._recording = False
            if self._writer is not None:
                self._writer.release()
                self._writer = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class _FpsCounter:
    """滑动窗口帧率计数器。"""
    def __init__(self, window: int = 30):
        self._window = window
        self._times: list[float] = []

    def tick(self):
        self._times.append(time.perf_counter())
        if len(self._times) > self._window:
            self._times.pop(0)

    def fps(self) -> float:
        if len(self._times) < 2:
            return 0.0
        elapsed = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / elapsed if elapsed > 0 else 0.0


# ──────────────────────────────────────────────────────────────────────
# LogiCameraWidget — 主界面
# ──────────────────────────────────────────────────────────────────────


class LogiCameraWidget(QWidget):
    """MX Brio 独立摄像头控制面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MX Brio 摄像头")
        self.setMinimumSize(1024, 700)

        self._thread: QThread | None = None
        self._capture: CameraCapture | None = None
        self._record_path: str | None = None

        self._init_ui()

    # ── UI 构造 ───────────────────────────────────────────────────────

    def _init_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(16, 12, 16, 12)
        main.setSpacing(10)

        # 标题
        main.addWidget(MDivider("Logitech MX Brio"))

        # 预览区
        self._preview = QLabel(self)
        self._preview.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self._preview.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #444;"
        )
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setText("（未连接）")
        main.addWidget(self._preview, alignment=Qt.AlignCenter)

        # 控制按钮
        btn_row = QHBoxLayout()
        self._btn_start = MPushButton("▶ 开始预览").primary()
        self._btn_start.setMinimumHeight(48)
        self._btn_start.clicked.connect(self._on_start)

        self._btn_record = MPushButton("⏺ 录制")
        self._btn_record.setMinimumHeight(48)
        self._btn_record.setEnabled(False)
        self._btn_record.clicked.connect(self._on_record)

        self._btn_stop = MPushButton("⏹ 停止")
        self._btn_stop.setMinimumHeight(48)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)

        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_record)
        btn_row.addWidget(self._btn_stop)
        main.addLayout(btn_row)

        # 状态栏
        self._lbl_status = MLabel()
        self._lbl_status.setText("状态: 就绪")
        main.addWidget(self._lbl_status)

    # ── 信号槽 ────────────────────────────────────────────────────────

    def _on_start(self):
        """打开摄像头，启动采集线程。"""
        if self._capture is not None:
            return
        capture = CameraCapture()
        if not capture.open(CAMERA_INDEX):
            QMessageBox.critical(self, "错误", "无法打开 MX Brio，请检查连接。")
            return

        self._capture = capture
        thread = QThread(self)
        capture.moveToThread(thread)
        capture.frame_ready.connect(self._on_frame)
        capture.stats_updated.connect(self._update_stats)
        capture.error.connect(self._on_error)
        capture.recording_finished.connect(self._on_record_finished)
        thread.started.connect(capture.start)
        thread.finished.connect(capture.deleteLater)
        self._thread = thread

        thread.start()
        self._set_ui_running(True)

    def _on_stop(self):
        """停止采集并释放。"""
        if self._capture is None:
            return
        cap = self._capture
        self._capture = None

        if cap._recording:
            cap.stop_record()
        cap.stop()

        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)

        self._set_ui_running(False)
        self._preview.setText("（已停止）")
        self._lbl_status.setText("状态: 已停止")

    def _on_record(self):
        """切换录制状态。"""
        if self._capture is None:
            return
        if not self._capture._recording:
            path = self._capture.start_record()
            if path:
                self._record_path = path
                self._btn_record.setText("⏺ 停止录制")
        else:
            self._capture.stop_record()

    # ── UI 回调 ───────────────────────────────────────────────────────

    def _on_frame(self, frame: np.ndarray):
        """收到新帧 → 显示。"""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        scale = min(PREVIEW_WIDTH / w, PREVIEW_HEIGHT / h, 1.0)
        disp_w = int(w * scale)
        disp_h = int(h * scale)
        if scale < 1.0:
            rgb = cv2.resize(rgb, (disp_w, disp_h), interpolation=cv2.INTER_NEAREST)
        bytes_per_line = rgb.strides[0]
        qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], bytes_per_line, QImage.Format_RGB888)
        self._preview.setPixmap(QPixmap.fromImage(qimg))

    def _update_stats(self, fps: float, record_sec: float):
        """更新状态显示。"""
        rec_str = f"{int(record_sec // 60):02d}:{int(record_sec % 60):02d}" if record_sec > 0 else "--:--"
        self._lbl_status.setText(
            f"帧率: {fps:.1f} fps  |  分辨率: {FRAME_WIDTH}×{FRAME_HEIGHT} @ {TARGET_FPS}fps"
        )
        if self._capture and self._capture._recording:
            self._lbl_status.setText(self._lbl_status.text() + f"  |  录制: {rec_str}")

    def _on_error(self, msg: str):
        self._lbl_status.setText(f"错误: {msg}")
        self._on_stop()

    def _on_record_finished(self, path: str):
        self._btn_record.setText("⏺ 录制")
        self._record_path = None
        QMessageBox.information(self, "录制完成", f"文件已保存:\n{path}")

    # ── 辅助 ──────────────────────────────────────────────────────────

    def _set_ui_running(self, running: bool):
        self._btn_start.setEnabled(not running)
        self._btn_record.setEnabled(running)
        self._btn_stop.setEnabled(running)

    def closeEvent(self, event):
        self._on_stop()
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────
# 独立运行
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    with application() as app:
        w = LogiCameraWidget()
        dayu_theme.apply(w)
        w.show()
        sys.exit(app.exec_())
