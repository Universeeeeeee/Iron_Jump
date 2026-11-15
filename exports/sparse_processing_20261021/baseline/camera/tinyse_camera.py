"""
tinyse_camera.py — OBSBOT Tiny SE 摄像头独立预览窗口

基于 dayu_widgets + qtpy + DirectShow 后端。
为步态分析系统提供实时视觉参考。

使用方式::

    python -m camera.tinyse_camera

设计目标:
- 独立运行，不与 ui/ 目录现有模块耦合
- 后期可导入主界面嵌入
"""

from __future__ import annotations

import csv
import ctypes
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

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
from dayu_widgets import dayu_theme
from dayu_widgets.check_box import MCheckBox
from dayu_widgets.collapse import MSectionItem
from dayu_widgets.combo_box import MComboBox
from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from dayu_widgets.qt import application

from .tinyse_dshow_capture import TinySeDShowCapture

BIN_DIR = Path(__file__).resolve().parent / "bin"
WRAPPER_DLL = BIN_DIR / "obsbot_c_api.dll"

FOV_OPTIONS = {0: "86°", 1: "78°", 2: "65°"}
EXPOSURE_OPTIONS = {
    0: "+0.0 EV", 3: "+0.3", 7: "+0.7", 10: "+1.0", 13: "+1.3", 17: "+1.7", 20: "+2.0",
    23: "+2.3", 27: "+2.7", 30: "+3.0",
    -30: "-3.0", -27: "-2.7", -23: "-2.3", -20: "-2.0", -17: "-1.7",
    -13: "-1.3", -10: "-1.0", -7: "-0.7", -3: "-0.3",
}
AI_SUB_MODE = {0: "标准", 1: "上半身", 2: "特写", 3: "无头", 4: "下半身", 5: "Butt"}
WDR_OPTIONS = {0: "关闭", 1: "DOL 2→1", 2: "Sensor"}


FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
TARGET_FPS = 100
PREVIEW_FPS = 30
PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540


@dataclass(frozen=True)
class TinySeFrameTiming:
    """DirectShow sample metadata plus host callback and decode times."""

    frame_index: int
    sample_time_s: float
    callback_time_s: float
    decoded_at_s: float


def mjpg_to_avi(
    mjpg_path: Path,
    csv_path: Path,
    output_path: Path | None = None,
    fps: float | None = None,
    cleanup: bool = True,
) -> Path:
    """将 DLL 录制的 raw .mjpg + .csv 索引 转换为 Kinovea 可读的 .avi。

    DLL 的 .mjpg 是纯 JPEG 帧拼接（无容器），Kinovea 不识别。
    此函数读 CSV 索引，逐帧解码后写入 AVI 容器（MJPG codec），
    并将实际输出帧的相对采样时间保存到同名 .timestamps.npy。

    Args:
        mjpg_path: DLL 生成的 .mjpg 文件
        csv_path:  DLL 生成的 .csv 索引文件
        output_path: 输出 .avi 路径，默认替换后缀
        fps: 帧率，默认从 CSV 采样时间推算

    Returns:
        输出 .avi 的 Path
    """
    import logging
    _log = logging.getLogger(__name__)

    if output_path is None:
        output_path = mjpg_path.with_suffix(".avi")

    # 1. 读取 CSV 帧索引
    frames_index: list[tuple[int, int, float]] = []  # (offset, length, sample_time)
    with open(csv_path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            frames_index.append((
                int(row["offset"]),
                int(row["length"]),
                float(row["sample_time"]),
            ))

    if not frames_index:
        raise RuntimeError(f"CSV 索引为空: {csv_path}")

    # 2. 推算帧率
    if fps is None and len(frames_index) >= 2:
        t0 = frames_index[0][2]
        t1 = frames_index[-1][2]
        if t1 > t0:
            fps = (len(frames_index) - 1) / (t1 - t0)
    if fps is None or not np.isfinite(fps) or fps <= 0:
        fps = 100.0

    _log.info("mjpg→avi: %d frames, %.2f fps", len(frames_index), fps)

    timestamps = []
    writer = None
    with open(mjpg_path, "rb") as fh:
        try:
            for offset, length, sample_time in frames_index:
                fh.seek(offset)
                jpeg_bytes = fh.read(length)
                frame = (
                    cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if jpeg_bytes else None
                )
                if frame is None:
                    continue
                if not np.isfinite(sample_time) or (timestamps and sample_time <= timestamps[-1]):
                    raise RuntimeError("录像采样时间无效或未递增")
                if writer is None:
                    h, w = frame.shape[:2]
                    writer = cv2.VideoWriter(
                        str(output_path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h)
                    )
                    if not writer.isOpened():
                        raise RuntimeError(f"VideoWriter 打开失败: {output_path}")
                if frame.shape[:2] != (h, w):
                    raise RuntimeError("录像帧尺寸发生变化")
                writer.write(frame)
                timestamps.append(sample_time)
        finally:
            if writer is not None:
                writer.release()
    written = len(timestamps)
    if not written:
        raise RuntimeError("录像没有可解码的画面")

    # Verify the delivered AVI before removing the only original copy.
    check = cv2.VideoCapture(str(output_path))
    try:
        if not check.isOpened() or int(check.get(cv2.CAP_PROP_FRAME_COUNT)) != written:
            raise RuntimeError("AVI 写入帧数校验失败")
        for index in (0, written - 1):
            check.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = check.read()
            if not ok or frame is None:
                raise RuntimeError("AVI 首尾画面校验失败")
    finally:
        check.release()

    times = np.asarray(timestamps, dtype=np.float64)
    times -= times[0]
    time_path = output_path.with_suffix(".timestamps.npy")
    temporary = time_path.with_suffix(".npy.tmp")
    try:
        with temporary.open("wb") as fh:
            np.save(fh, times, allow_pickle=False)
        if not np.array_equal(np.load(temporary, allow_pickle=False), times):
            raise RuntimeError("录像时间文件校验失败")
        temporary.replace(time_path)
    finally:
        temporary.unlink(missing_ok=True)
    _log.info("mjpg→avi: wrote %d frames → %s", written, output_path)

    if cleanup:
        try:
            mjpg_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            csv_path.unlink(missing_ok=True)
        except OSError:
            pass

    return output_path


def _log_timing(message: str) -> None:
    print(f"[TinySE Timing] {message}", flush=True)


def _bind_control_fns(dll: ctypes.CDLL) -> None:
    """为 DLL 绑定控制函数签名。"""
    dll.obsbot_refresh_devices.argtypes = [ctypes.c_int32]
    dll.obsbot_refresh_devices.restype = ctypes.c_int32
    dll.obsbot_close.argtypes = []
    dll.obsbot_close.restype = None
    for name in (
        "obsbot_set_camera_mirror",
        "obsbot_set_ai_mode",
        "obsbot_set_auto_focus",
        "obsbot_set_manual_focus",
        "obsbot_set_exposure_compensation",
        "obsbot_set_anti_flicker",
        "obsbot_set_fov",
        "obsbot_set_wdr",
    ):
        fn = getattr(dll, name)
        fn.argtypes = [ctypes.c_int32, ctypes.c_int32]
        fn.restype = ctypes.c_int32
    dll.obsbot_set_ai_mode.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]


class TinySeCameraControl:
    """Tiny SE SDK 参数控制。

    约束：SDK 和 DirectShow 不能同时占用 UVC 设备。
    所有设置必须在采集启动前完成，运行时修改无效。
    """

    def __init__(self, device_index: int = 0):
        if not WRAPPER_DLL.exists():
            raise FileNotFoundError(f"wrapper DLL not found: {WRAPPER_DLL}")
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(str(BIN_DIR))
        self._dll = ctypes.CDLL(str(WRAPPER_DLL))
        _bind_control_fns(self._dll)
        self._idx = device_index
        self._dirty = False

    def init(self) -> bool:
        """采集前调用一次。填充设备缓存，返回是否成功。"""
        count = self._dll.obsbot_refresh_devices(500)
        if count <= 0:
            # 首次检测可能较慢，重试一次
            count = self._dll.obsbot_refresh_devices(5000)
        return count > 0

    def apply_pending(self):
        """应用所有待定设置（采集启动前调用一次）。"""
        self._dirty = False

    # ── 镜像 ──
    def set_mirror(self, on: bool) -> int:
        """硬件水平镜像。替代 cv2.flip。"""
        return self._dll.obsbot_set_camera_mirror(self._idx, 1 if on else 0)

    # ── AI 追踪 ──
    def set_ai_lower_body(self) -> int:
        """下半身追踪：AiWorkModeHuman(2) + AiSubModeLowerBody(4)。"""
        return self._dll.obsbot_set_ai_mode(self._idx, 2, 4)

    def set_ai_off(self) -> int:
        """关闭 AI 追踪。"""
        return self._dll.obsbot_set_ai_mode(self._idx, 0, 0)

    def set_ai_mode(self, sub_mode: int) -> int:
        """sub_mode: 0=标准 1=上半身 2=特写 3=无头 4=下半身 5=Butt"""
        return self._dll.obsbot_set_ai_mode(self._idx, 2, sub_mode)

    # ── 对焦 ──
    def set_auto_focus(self, on: bool) -> int:
        """on=True 自动对焦，on=False 手动对焦。"""
        return self._dll.obsbot_set_auto_focus(self._idx, 1 if on else 0)

    def set_manual_focus(self, value: int) -> int:
        """手动对焦值 0~100。"""
        return self._dll.obsbot_set_manual_focus(self._idx, value)

    # ── 曝光 ──
    def set_exposure_compensation(self, ev_index: int) -> int:
        """离散 EV 值，见 EXPOSURE_OPTIONS 白名单。"""
        return self._dll.obsbot_set_exposure_compensation(self._idx, ev_index)

    # ── 抗频闪 ──
    def set_anti_flicker(self, freq: int) -> int:
        """0=60Hz, 1=50Hz。"""
        return self._dll.obsbot_set_anti_flicker(self._idx, freq)

    # ── 视野 ──
    def set_fov(self, fov: int) -> int:
        """0=86°, 1=78°, 2=65°。"""
        return self._dll.obsbot_set_fov(self._idx, fov)

    # ── HDR/WDR ──
    def set_wdr(self, wdr: int) -> int:
        """0=Off, 1=DOL2to1, 2=Sensor。"""
        return self._dll.obsbot_set_wdr(self._idx, wdr)

    def close(self):
        """Release this Python handle without shutting down the process SDK singleton."""
        self._dll = None


class TinySeCameraCapture(QObject):
    frame_ready = Signal(np.ndarray)
    analysis_frame_ready = Signal(object, float)
    analysis_frame_timed_ready = Signal(object, object)
    stats_updated = Signal(float, float)
    recording_finished = Signal(str)
    started = Signal()
    error = Signal(str)

    def __init__(
        self,
        device_needle: str = "OBSBOT Tiny SE",
        width: int = FRAME_WIDTH,
        height: int = FRAME_HEIGHT,
        fps: int = TARGET_FPS,
        preview_fps: int = PREVIEW_FPS,
        parent=None,
    ):
        super().__init__(parent)
        self._device_needle = device_needle
        self._width = width
        self._height = height
        self._fps = fps
        self._preview_interval = 1.0 / max(1, preview_fps)
        self._last_preview_time = 0.0
        self._capture: TinySeDShowCapture | None = None
        self._running = False
        self._stop_requested = threading.Event()
        self._recording = False
        self._record_path: Path | None = None
        self._csv_path: Path | None = None
        self._record_start = 0.0
        self._record_lock = threading.Lock()
        self._record_finalizing = False
        self._record_finalize_thread: threading.Thread | None = None
        self._record_preserve_raw = False
        self._last_record_stats = None
        self._preview_lock = threading.Lock()
        self._preview_wake = threading.Event()
        self._pending_mjpg = None
        self._mirror = True  # 软件镜像
        self._preview_enabled = True

    @property
    def is_recording(self) -> bool:
        with self._record_lock:
            return self._recording

    @property
    def is_record_busy(self) -> bool:
        with self._record_lock:
            return self._recording or self._record_finalizing

    def open(self) -> bool:
        if self._capture is not None:
            return True
        try:
            start = time.perf_counter()
            self._capture = TinySeDShowCapture(
                device_needle=self._device_needle,
                width=self._width,
                height=self._height,
                fps=self._fps,
                on_timed_frame=self._on_mjpg_frame,
            )
            _log_timing(f"dshow.create={time.perf_counter() - start:.3f}s")
            return True
        except Exception as exc:
            self.error.emit(str(exc))
            self._capture = None
            return False

    def start(self):
        total_start = time.perf_counter()
        if self._stop_requested.is_set():
            self._cleanup()
            return
        if not self.open():
            self._running = False
            _log_timing(f"capture.worker.start.failed={time.perf_counter() - total_start:.3f}s")
            return

        capture = self._capture
        if capture is None:
            self.error.emit("Tiny SE capture was not initialized")
            self._running = False
            _log_timing(f"capture.worker.start.failed={time.perf_counter() - total_start:.3f}s")
            return

        try:
            start = time.perf_counter()
            capture.start()
            _log_timing(f"dshow.start={time.perf_counter() - start:.3f}s")
            self._running = not self._stop_requested.is_set()
            if self._running:
                self.started.emit()
            _log_timing(f"capture.worker.ready={time.perf_counter() - total_start:.3f}s")
            next_stats = 0.0
            while self._running and not self._stop_requested.is_set():
                self._preview_wake.wait(.02)
                self._preview_wake.clear()
                with self._preview_lock:
                    pending, self._pending_mjpg = self._pending_mjpg, None
                if pending is not None and self._preview_enabled:
                    self._decode_preview_frame(*pending)
                if time.perf_counter() < next_stats:
                    continue
                next_stats = time.perf_counter() + .2
                stats = capture.stats()
                with self._record_lock:
                    recording = self._recording
                    record_start = self._record_start
                record_sec = time.perf_counter() - record_start if recording else 0.0
                self.stats_updated.emit(stats.wall_fps, record_sec)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._cleanup()

    def stop(self):
        # The capture worker owns native stop/close in its finally block.
        # Calling stop here can race that cleanup and use an already freed handle.
        self._stop_requested.set()
        self._running = False
        self._preview_wake.set()

    def start_record(
        self,
        stem: str | Path | None = None,
        *,
        preserve_raw: bool = False,
    ) -> str | None:
        with self._record_lock:
            if self._capture is None or self._recording or self._record_finalizing:
                return None
            capture = self._capture
        try:
            mjpg_path, csv_path = capture.start_record(stem)
        except Exception as exc:
            self.error.emit(str(exc))
            return None
        with self._record_lock:
            self._recording = True
            self._record_path = mjpg_path
            self._csv_path = csv_path
            self._record_preserve_raw = preserve_raw
            self._record_start = time.perf_counter()
        return str(mjpg_path)

    def stop_record(self, wait: bool = False) -> bool:
        thread_to_join: threading.Thread | None = None
        with self._record_lock:
            if self._record_finalizing and not self._recording:
                thread_to_join = self._record_finalize_thread
                if not wait:
                    return False
                if thread_to_join is None:
                    return True
            elif self._capture is None or not self._recording:
                return False
            else:
                capture = self._capture
                mjpg_path = self._record_path
                csv_path = self._csv_path
                preserve_raw = self._record_preserve_raw
                self._recording = False
                self._record_path = None
                self._csv_path = None
                self._record_preserve_raw = False
                self._record_finalizing = True
                if wait:
                    thread_to_join = None
                else:
                    thread = threading.Thread(
                        target=self._finalize_recording,
                        args=(capture, mjpg_path, csv_path, preserve_raw),
                        name="TinySeRecordFinalize",
                        daemon=True,
                    )
                    self._record_finalize_thread = thread
                    thread.start()
                    return True

        if thread_to_join is not None:
            if thread_to_join is not threading.current_thread():
                thread_to_join.join()
            return True

        self._finalize_recording(capture, mjpg_path, csv_path, preserve_raw)
        return True

    def _finalize_recording(
        self,
        capture: TinySeDShowCapture,
        mjpg_path: Path | None,
        csv_path: Path | None,
        preserve_raw: bool = False,
    ) -> None:
        avi_path = None
        failure = None
        try:
            self._last_record_stats = capture.stop_record()
            if not preserve_raw and mjpg_path is not None and csv_path is not None:
                avi_path = mjpg_to_avi(mjpg_path, csv_path)
        except Exception as exc:
            failure = f"录像保存失败（保留原始 MJPEG/CSV）: {exc}"
        finally:
            with self._record_lock:
                self._record_finalizing = False
                if self._record_finalize_thread is threading.current_thread():
                    self._record_finalize_thread = None
        if failure is not None:
            self.error.emit(failure)
        elif avi_path is not None:
            self.recording_finished.emit(str(avi_path))

    @property
    def last_record_stats(self):
        return self._last_record_stats

    def set_mirror(self, on: bool):
        self._mirror = on

    def set_preview_enabled(self, enabled: bool):
        self._preview_enabled = enabled
        if enabled:
            self._last_preview_time = 0.0

    def _on_mjpg_frame(
        self,
        data: bytes,
        frame_index: int,
        sample_time: float,
        callback_time_s: float,
    ) -> None:
        if not self._preview_enabled:
            return

        if callback_time_s - self._last_preview_time < self._preview_interval:
            return
        self._last_preview_time = callback_time_s

        # Keep the DirectShow callback short: decoding and Python consumers must
        # not hold up native capture or let old compressed frames accumulate.
        with self._preview_lock:
            self._pending_mjpg = (data, frame_index, sample_time, callback_time_s)
        self._preview_wake.set()

    def _decode_preview_frame(self, data, frame_index, sample_time, callback_time_s):
        encoded = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            return
        decoded_at_s = time.perf_counter()
        timing = TinySeFrameTiming(
            frame_index=frame_index,
            sample_time_s=sample_time,
            callback_time_s=callback_time_s,
            decoded_at_s=decoded_at_s,
        )
        self.analysis_frame_timed_ready.emit(frame, timing)
        self.analysis_frame_ready.emit(frame, decoded_at_s)
        if self._mirror:
            frame = cv2.flip(frame, 1)
        self.frame_ready.emit(frame)

    def _cleanup(self):
        self._running = False
        if self.is_record_busy:
            self.stop_record(wait=True)
        if self._capture is not None:
            start = time.perf_counter()
            self._capture.close()
            _log_timing(f"dshow.close={time.perf_counter() - start:.3f}s")
            self._capture = None
        with self._preview_lock:
            self._pending_mjpg = None


class TinySeCameraWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OBSBOT Tiny SE")
        self.resize(1100, 860)
        screen = self.screen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )
        self._thread: QThread | None = None
        self._capture: TinySeCameraCapture | None = None
        self._control: TinySeCameraControl | None = None
        self._record_path: str | None = None
        self._preview_start_time: float | None = None
        self._preview_active = False

        layout = QVBoxLayout(self)
        layout.addWidget(MDivider("OBSBOT Tiny SE"))

        self._preview = QLabel("Preview")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self._preview.setStyleSheet("background: #111; color: #aaa;")
        layout.addWidget(self._preview)

        self._stats = MLabel("Idle")
        layout.addWidget(self._stats)

        buttons = QHBoxLayout()
        self._btn_start = MPushButton("Start Preview").primary()
        self._btn_stop = MPushButton("Stop")
        self._btn_record = MPushButton("Record")
        self._btn_stop.setEnabled(False)
        self._btn_record.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_record.clicked.connect(self._on_record)
        buttons.addWidget(self._btn_start)
        buttons.addWidget(self._btn_stop)
        buttons.addWidget(self._btn_record)
        layout.addLayout(buttons)

        # ── 控制面板 ──
        ctl_container = QWidget()
        ctl = QVBoxLayout(ctl_container)
        ctl.setContentsMargins(8, 4, 8, 4)
        ctl.setSpacing(6)

        row1 = QHBoxLayout()
        self._chk_mirror = MCheckBox("镜像")
        self._chk_mirror.stateChanged.connect(self._on_mirror)
        row1.addWidget(self._chk_mirror)
        self._cmb_fov = MComboBox()
        for k, v in FOV_OPTIONS.items():
            self._cmb_fov.addItem(v, k)
        self._cmb_fov.currentIndexChanged.connect(self._on_fov_changed)
        row1.addWidget(MLabel("视野:"))
        row1.addWidget(self._cmb_fov)
        row1.addStretch()
        ctl.addLayout(row1)

        row2 = QHBoxLayout()
        self._cmb_ai = MComboBox()
        for k, v in sorted(AI_SUB_MODE.items()):
            self._cmb_ai.addItem(v, k)
        self._cmb_ai.setCurrentIndex(4)  # 默认下半身
        row2.addWidget(MLabel("AI 追踪:"))
        row2.addWidget(self._cmb_ai)
        self._btn_ai_go = MPushButton("激活")
        self._btn_ai_go.clicked.connect(self._on_ai_go)
        row2.addWidget(self._btn_ai_go)
        self._btn_ai_off = MPushButton("关闭追踪")
        self._btn_ai_off.clicked.connect(self._on_ai_off)
        row2.addWidget(self._btn_ai_off)
        row2.addStretch()
        ctl.addLayout(row2)

        row3 = QHBoxLayout()
        self._chk_af = MCheckBox("自动对焦")
        self._chk_af.setChecked(True)
        self._chk_af.stateChanged.connect(self._on_af_changed)
        row3.addWidget(self._chk_af)
        self._cmb_exp = MComboBox()
        for k, v in sorted(EXPOSURE_OPTIONS.items()):
            self._cmb_exp.addItem(v, k)
        self._cmb_exp.setCurrentText("+0.0 EV")
        self._cmb_exp.currentIndexChanged.connect(self._on_exp_changed)
        row3.addWidget(MLabel("曝光:"))
        row3.addWidget(self._cmb_exp)
        row3.addStretch()
        ctl.addLayout(row3)

        row4 = QHBoxLayout()
        self._cmb_flicker = MComboBox()
        self._cmb_flicker.addItem("60Hz", 0)
        self._cmb_flicker.addItem("50Hz", 1)
        self._cmb_flicker.currentIndexChanged.connect(self._on_flicker_changed)
        row4.addWidget(MLabel("抗频闪:"))
        row4.addWidget(self._cmb_flicker)
        self._cmb_wdr = MComboBox()
        for k, v in WDR_OPTIONS.items():
            self._cmb_wdr.addItem(v, k)
        self._cmb_wdr.currentIndexChanged.connect(self._on_wdr_changed)
        row4.addWidget(MLabel("HDR:"))
        row4.addWidget(self._cmb_wdr)
        row4.addStretch()
        ctl.addLayout(row4)

        self._ctl_section = MSectionItem(
            "摄像头控制", widget=ctl_container, expand=False
        )
        layout.addWidget(self._ctl_section)

    def _apply_control_settings(self, ctl: TinySeCameraControl):
        start = time.perf_counter()
        ctl.set_fov(int(self._cmb_fov.currentData() or 0))
        ctl.set_auto_focus(self._chk_af.isChecked())
        ctl.set_exposure_compensation(int(self._cmb_exp.currentData() or 0))
        ctl.set_anti_flicker(int(self._cmb_flicker.currentData() or 0))
        ctl.set_wdr(int(self._cmb_wdr.currentData() or 0))
        ctl.set_ai_off()
        _log_timing(f"control.apply={time.perf_counter() - start:.3f}s")

    def _ensure_control(self, apply_settings: bool = True) -> bool:
        if self._control is not None:
            if apply_settings:
                self._apply_control_settings(self._control)
            return True
        try:
            start = time.perf_counter()
            ctl = TinySeCameraControl(0)
            _log_timing(f"control.create={time.perf_counter() - start:.3f}s")
            start = time.perf_counter()
            initialized = ctl.init()
            _log_timing(f"control.init={time.perf_counter() - start:.3f}s ok={initialized}")
            if not initialized:
                ctl.close()
                QMessageBox.warning(self, "SDK 控制不可用", "未检测到 OBSBOT Tiny SE SDK 设备")
                return False
            self._control = ctl
            if apply_settings:
                self._apply_control_settings(ctl)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "SDK 控制不可用", str(exc))
            self._control = None
            return False

    def _report_control_result(self, action: str, ret: int):
        if ret < 0:
            QMessageBox.warning(self, "SDK 控制失败", f"{action}失败，返回码: {ret}")

    def _release_control(self):
        ctl = self._control
        self._control = None
        if ctl is not None:
            start = time.perf_counter()
            ctl.close()
            _log_timing(f"control.close={time.perf_counter() - start:.3f}s")

    def _on_start(self):
        if self._thread is not None:
            self._preview_active = True
            self._preview_start_time = time.perf_counter()
            if self._capture is not None:
                self._capture.set_preview_enabled(True)
            self._set_running(True)
            return
        total_start = time.perf_counter()
        self._preview_start_time = total_start
        self._preview_active = True
        _log_timing("ui.start.click")
        self._ensure_control()
        # 2. 启动采集
        self._thread = QThread(self)
        self._capture = TinySeCameraCapture()
        self._capture.moveToThread(self._thread)
        self._thread.started.connect(self._capture.start)
        self._capture.frame_ready.connect(self._on_frame)
        self._capture.stats_updated.connect(self._on_stats)
        self._capture.recording_finished.connect(self._on_recording_finished)
        self._capture.error.connect(self._on_error)
        self._thread.finished.connect(self._thread.deleteLater)
        start = time.perf_counter()
        self._thread.start()
        _log_timing(f"ui.thread.start={time.perf_counter() - start:.3f}s")
        self._set_running(True)
        _log_timing(f"ui.start.total={time.perf_counter() - total_start:.3f}s")

    def _on_stop(self):
        total_start = time.perf_counter()
        _log_timing("ui.stop.click")
        capture = self._capture
        if capture is not None:
            if capture.is_recording:
                if capture.stop_record():
                    self._btn_record.setText("Saving...")
                    self._btn_record.setEnabled(False)
            capture.set_preview_enabled(False)
        self._preview_active = False
        self._preview_start_time = None
        self._set_running(False)
        _log_timing(f"ui.stop.total={time.perf_counter() - total_start:.3f}s")

    def _shutdown_capture(self):
        capture = self._capture
        thread = self._thread
        if capture is not None:
            if capture.is_record_busy:
                capture.stop_record(wait=True)
            start = time.perf_counter()
            capture.stop()
            _log_timing(f"ui.capture.stop.call={time.perf_counter() - start:.3f}s")
        if thread is not None:
            start = time.perf_counter()
            thread.quit()
            finished = thread.wait(2000)
            _log_timing(f"ui.thread.wait={time.perf_counter() - start:.3f}s finished={finished}")
        self._thread = None
        self._capture = None
        self._preview_active = False
        self._preview_start_time = None
        self._set_running(False)

    def _on_record(self):
        capture = self._capture
        if capture is None:
            return
        if capture.is_record_busy and not capture.is_recording:
            return
        if not capture.is_recording:
            path = capture.start_record()
            if path:
                self._record_path = path
                self._btn_record.setText("Stop Recording")
        else:
            if capture.stop_record():
                self._btn_record.setText("Saving...")
                self._btn_record.setEnabled(False)

    def _on_frame(self, frame: np.ndarray):
        if not self._preview_active:
            return
        if self._preview_start_time is not None:
            _log_timing(f"ui.first_frame={time.perf_counter() - self._preview_start_time:.3f}s")
            self._preview_start_time = None
        preview = cv2.resize(frame, (PREVIEW_WIDTH, PREVIEW_HEIGHT), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        self._preview.setPixmap(QPixmap.fromImage(image))

    def _on_stats(self, fps: float, record_sec: float):
        if not self._preview_active:
            return
        rec = f" recording {record_sec:.1f}s" if record_sec > 0 else ""
        self._stats.setText(f"Capture {fps:.2f} fps{rec}")

    def _on_recording_finished(self, path: str):
        self._record_path = None
        self._btn_record.setText("Record")
        self._btn_record.setEnabled(self._preview_active)
        QMessageBox.information(self, "Recording Finished", path)

    def _on_error(self, message: str):
        QMessageBox.critical(self, "Tiny SE Error", message)
        self._shutdown_capture()

    # ── 控制面板事件（即时发送；采集运行中可能被驱动拒绝，重启预览保证生效）──

    def _ctl(self):
        return self._control

    def _on_mirror(self, _state: int):
        cap = self._capture
        if cap is not None:
            cap.set_mirror(self._chk_mirror.isChecked())

    def _on_fov_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_fov.currentData()
            if data is not None:
                ctl.set_fov(int(data))

    def _on_ai_go(self):
        if not self._ensure_control(apply_settings=False):
            return
        ctl = self._ctl()
        data = self._cmb_ai.currentData()
        if ctl is not None and data is not None:
            self._report_control_result("AI 追踪", ctl.set_ai_mode(int(data)))

    def _on_ai_off(self):
        if not self._ensure_control(apply_settings=False):
            return
        ctl = self._ctl()
        if ctl is not None:
            self._report_control_result("关闭 AI 追踪", ctl.set_ai_off())

    def _on_af_changed(self, _state: int):
        ctl = self._ctl()
        if ctl is not None:
            ctl.set_auto_focus(self._chk_af.isChecked())

    def _on_exp_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_exp.currentData()
            if data is not None:
                ctl.set_exposure_compensation(int(data))

    def _on_flicker_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_flicker.currentData()
            if data is not None:
                ctl.set_anti_flicker(int(data))

    def _on_wdr_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_wdr.currentData()
            if data is not None:
                ctl.set_wdr(int(data))

    def _set_running(self, running: bool):
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._btn_record.setEnabled(running)
        # 控制面板在采集期间保持可用；DShow 运行时部分命令可能被驱动拒绝，
        # 但用户可随时尝试。需重启预览才能保证全部生效。
        if not running:
            if self._capture is not None and self._capture.is_record_busy:
                self._btn_record.setText("Saving...")
                self._btn_record.setEnabled(False)
            else:
                self._btn_record.setText("Record")
            self._stats.setText("Idle")

    def closeEvent(self, event):
        self._shutdown_capture()
        self._release_control()
        super().closeEvent(event)


if __name__ == "__main__":
    with application() as app:
        widget = TinySeCameraWidget()
        dayu_theme.apply(widget)
        widget.show()
        sys.exit(app.exec_())
