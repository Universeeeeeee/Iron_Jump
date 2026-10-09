"""
usb_worker.py — USB 硬件数据采集 Worker（基于 receive.CyUsbInterfaceDevice）

从 start_test.py 提取为独立公共模块，供 start_test.py / 2data_show.py / 3data_show.py / led_con.py 共用。
"""
from __future__ import annotations

import os
import math
import threading
import time

from qtpy.QtCore import QObject, Signal, Slot, QTimer

from hardware.protocol import E_ACK, UploadDataSubPack
from hardware.sensor_frame import AcquisitionIssue, DeviceLayout, SensorFrameAssembler
from hardware.beam_filter import BeamDisplayFilter

try:
    from .receive import CyUsbInterfaceDevice, E_DATA_REPORT
except ImportError:
    try:
        from receive import CyUsbInterfaceDevice, E_DATA_REPORT
    except ImportError:
        CyUsbInterfaceDevice = None
        E_DATA_REPORT = 0x82


LED_HEALTH_TARGET_FRAMES = 64
LED_HEALTH_MIN_FRAMES = 20
LED_HEALTH_TIMEOUT_S = 0.8
CAPTURE_START_TIMEOUT_S = 1.0


def summarize_led_health(contact_frames: list[list[int]], bit_count: int = 96) -> dict:
    """Summarize per-LED continuity from a short unobstructed sampling window."""
    frames = [
        [1 if int(bit) else 0 for bit in frame[:bit_count]]
        for frame in contact_frames
        if len(frame) == bit_count
    ]
    sample_count = len(frames)
    if sample_count < LED_HEALTH_MIN_FRAMES:
        return {
            "status": "insufficient",
            "sample_count": sample_count,
            "disconnected_leds": [],
            "flickering_leds": [],
        }

    disconnected: list[int] = []
    flickering: list[int] = []
    transition_threshold = max(4, math.ceil((sample_count - 1) * 0.10))
    for led_index in range(bit_count):
        values = [frame[led_index] for frame in frames]
        if all(values):
            disconnected.append(led_index + 1)
            continue
        transitions = sum(
            current != previous
            for previous, current in zip(values, values[1:])
        )
        if transitions >= transition_threshold:
            flickering.append(led_index + 1)

    return {
        "status": "warning" if disconnected or flickering else "normal",
        "sample_count": sample_count,
        "disconnected_leds": disconnected,
        "flickering_leds": flickering,
    }


class UsbWorker(QObject):
    data_received = Signal(str)   # 文本日志（HEX）- 节流
    device_state_changed = Signal(str, str)  # state, user-facing detail
    sensor_frame_received = Signal(object)  # SensorFrame: complete, unfiltered, all modules
    layout_detected = Signal(object)  # Verified DeviceLayout, emitted before the first frame
    acquisition_issue = Signal(object)  # AcquisitionIssue: never substitute a clear frame
    led_bits_signal = Signal(list)  # 全设备 LED 位图 (物理语义: 1=LED亮/未遮挡) - 节流，供 UI
    led_contact_signal = Signal(list)  # 全设备 LED 位图 (接触语义: 1=遮挡/触地) - 节流，供 UI
    raw_contact_signal = Signal(list, float)  # 单段兼容接口，保留 perf_counter 时间基准
    led_health_changed = Signal(dict)  # 轻量 LED 通断/闪烁检查结果

    def __init__(self, dll_path=None, vid=0x04B4, pid=0x1004, timeout_ms=10, chunk_size=2048,
                 *, layout: DeviceLayout | None = None, capture_command_required=None,
                 legacy_frame_signals=True):
        super().__init__()
        self.dll_path = dll_path
        self.vid = int(vid)
        self.pid = int(pid)
        self.timeout_ms = int(timeout_ms)
        self.chunk_size = int(chunk_size)
        self.legacy_frame_signals = legacy_frame_signals
        if layout is None:
            count_spec = os.getenv("DAYU_SEGMENT_COUNT")
            order_spec = os.getenv("DAYU_SEGMENT_ORDER", "")
            order = tuple(int(i) for i in order_spec.split(",")) if order_spec else None
            count = int(count_spec) if count_spec else (len(order) if order else None)
        if layout is None and count is not None:
            layout = DeviceLayout.linear(
                count, wire_order=order,
            )
        self.layout = layout
        self.capture_command_required = (
            os.getenv("DAYU_CAPTURE_COMMAND", "1") == "1"
            if capture_command_required is None else capture_command_required
        )
        self._assembler = SensorFrameAssembler(layout)
        self._layout_announced = False
        self._frame_lock = threading.Lock()
        self._discard_frames = False
        self._start_ack_pending = False
        self._start_ack = threading.Event()
        self._start_ack_code = None
        self.dev = None
        self._capturing = False
        self._stop = threading.Event()
        # 节流设置（默认日志 100ms、LED 由目标采样率推导，可用环境变量覆盖）
        self.log_interval = max(0.0, float(os.getenv("DAYU_LOG_INTERVAL_MS", "100")) / 1000.0)
        target_rate = max(1.0, float(os.getenv("DAYU_TARGET_RATE_HZ", "200")))
        led_interval_override = os.getenv("DAYU_LED_INTERVAL_MS")
        if led_interval_override:
            self.led_interval = max(0.0, float(led_interval_override) / 1000.0)
        else:
            self.led_interval = 1.0 / target_rate
        self.target_rate_hz = target_rate
        self.debug_raw = os.getenv("DAYU_DEBUG_USB_RAW", "0") == "1"
        self._last_log_ts = 0.0
        self._last_led_ts = 0.0
        self._pending_hex = None
        self._pending_bits = None
        self._flush_timer = None
        self._health_frames: list[list[int]] = []
        self._health_filter = BeamDisplayFilter(10)
        self._health_first_sample = None
        self._health_check_active = False
        self._health_owns_capture = False
        self._health_deadline = 0.0
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(50)
        self._health_timer.timeout.connect(self._poll_led_health)

    # --- 工具 ---
    def _emit(self, msg: str):
        try:
            self.data_received.emit(msg)
        except Exception:
            print(msg)

    def _emit_state(self, state: str, message: str) -> None:
        self.device_state_changed.emit(state, message)
        self._emit(message)

    def _extract_payload(self, subpack) -> bytes:
        # 适配多种可能字段名
        cand_names = ["body", "payload", "data", "buffer", "buf"]
        buf = None
        for name in cand_names:
            if hasattr(subpack, name):
                try:
                    val = getattr(subpack, name)
                    if val is not None:
                        buf = val
                        break
                except Exception:
                    pass
        if buf is None:
            return b""
        try:
            raw = bytes(buf)
        except Exception:
            try:
                raw = bytes(bytearray(buf))
            except Exception:
                raw = b""
        # 若存在 bufferLen，进行安全截断
        try:
            blen = int(getattr(subpack, "bufferLen"))
            if 0 < blen <= len(raw):
                raw = raw[:blen]
        except Exception:
            pass
        return raw

    def _queue_update(self, hex_text=None, bits=None):
        if hex_text:
            self._pending_hex = hex_text
        if bits is not None:
            self._pending_bits = bits
        self._maybe_flush()

    def _maybe_flush(self, force=False):
        now = time.perf_counter()
        if self._pending_hex and (force or self.log_interval == 0.0 or now - self._last_log_ts >= self.log_interval):
            msg = self._pending_hex
            self._pending_hex = None
            self._last_log_ts = now
            try:
                self.data_received.emit(msg)
            except Exception:
                pass
        if self._pending_bits is not None and (force or self.led_interval == 0.0 or now - self._last_led_ts >= self.led_interval):
            bits_to_emit = self._pending_bits
            self._pending_bits = None
            self._last_led_ts = now
            try:
                self.led_bits_signal.emit(bits_to_emit)
            except Exception:
                pass
            # 同时发射接触语义信号 (1=遮挡/触地)
            try:
                contact_bits = [1 - b for b in bits_to_emit]
                self.led_contact_signal.emit(contact_bits)
            except Exception:
                pass

    def _on_flush_timer(self):
        with self._frame_lock:
            self._assembler.expire(time.perf_counter_ns())
            issues = self._assembler.pop_issues()
        for issue in issues:
            self.acquisition_issue.emit(issue)
        self._maybe_flush()

    def _ensure_timer(self):
        if self._flush_timer is not None:
            return
        candidates = [val for val in (self.log_interval, self.led_interval) if val > 0.0]
        if not candidates:
            return
        interval_s = min(candidates)
        self._flush_timer = QTimer()
        self._flush_timer.setInterval(max(1, int(interval_s * 1000)))
        self._flush_timer.timeout.connect(self._on_flush_timer)
        self._flush_timer.start()

    # --- 设备回调 ---
    def _on_bytes(self, data: bytes):
        if self.debug_raw:
            self._queue_update(hex_text=f"RAW len={len(data)} head={data[:16].hex(' ')}")

    def _on_frame(self, frame_type, ack, subpack, status):
        with self._frame_lock:
            if frame_type == E_ACK:
                if self._start_ack_pending and ack is not None:
                    self._start_ack_code = ack.ACK
                    self._start_ack_pending = False
                    self._discard_frames = ack.ACK != 0
                    self._start_ack.set()
                return
            if self._discard_frames:
                return
        if frame_type != E_DATA_REPORT or subpack is None:
            return
        try:
            packet = UploadDataSubPack(
                frameIdx=int(subpack.frameIdx), packNum=int(subpack.packNum),
                packIdx=int(subpack.packIdx), buffer=self._extract_payload(subpack),
            )
        except (TypeError, ValueError, AttributeError):
            self.acquisition_issue.emit(AcquisitionIssue("invalid_packet", -1))
            return
        with self._frame_lock:
            frame = self._assembler.feed(packet, time.perf_counter_ns())
            issues = self._assembler.pop_issues()
        for issue in issues:
            self.acquisition_issue.emit(issue)
        if frame is None:
            return
        if not self._layout_announced:
            self.layout = frame.layout
            self._layout_announced = True
            self.layout_detected.emit(frame.layout)
        self._publish_frame(frame)

    def _publish_frame(self, frame):
        """Deliver a complete sample; monitors can avoid unused legacy signals."""
        self.sensor_frame_received.emit(frame)
        self._record_led_health_frame(frame)
        # The main controller consumes SensorFrame only. Avoid building duplicate
        # lists and HEX text for the single-meter viewer's compatibility signals.
        if not self.legacy_frame_signals:
            return
        contacts = list(frame.contact_bits)
        # Old algorithms expect a single 96-beam module and host clock. Never
        # silently truncate a multi-module frame into that compatibility path.
        if len(self.layout.segments) == 1:
            self.raw_contact_signal.emit(contacts, time.perf_counter())
        self._queue_update(
            hex_text=frame.wire_payload.hex(" "), bits=[1 - bit for bit in contacts],
        )

    def _discard_startup_input(self):
        """Drain old DATA and ACK bytes while the FPGA is stopped, without a reader."""
        quiet_since = time.perf_counter()
        deadline = quiet_since + CAPTURE_START_TIMEOUT_S
        while time.perf_counter() < deadline:
            data = self.dev.read(self.chunk_size, timeout_ms=max(1, min(self.timeout_ms, 20)))
            now = time.perf_counter()
            if data:
                quiet_since = now
            elif now - quiet_since >= 0.020:
                return
            else:
                time.sleep(0.001)
        raise RuntimeError("清理上一轮采集数据超时，请重新连接设备")

    def _close_frame_gate(self):
        with self._frame_lock:
            self._discard_frames = True
            self._start_ack_pending = False

    def _on_protocol_issue(self, code):
        with self._frame_lock:
            if self._discard_frames:
                return
        self.acquisition_issue.emit(AcquisitionIssue(code, -1))

    # --- 生命周期 ---
    @Slot()
    def connect_device(self):
        """Open the USB device without starting the acquisition stream."""
        self._stop.clear()
        if self.dev is not None:
            self._emit_state("connected", "设备已连接")
            return
        self._emit_state("connecting", "正在连接设备...")
        if CyUsbInterfaceDevice is None:
            self._emit_state(
                "error",
                "无法导入 receive.CyUsbInterfaceDevice，请检查 receive.py 与 DLL 可用性。",
            )
            return
        try:
            self.dev = CyUsbInterfaceDevice(self.dll_path)
        except Exception as e:
            self.dev = None
            self._emit_state("error", f"加载 DLL 失败: {e}")
            return
        if not self.dev.open(self.vid, self.pid):
            self.dev = None
            self._emit_state(
                "error",
                f"打开设备失败: VID=0x{self.vid:04X} PID=0x{self.pid:04X}",
            )
            return
        self._emit_state(
            "connected",
            f"设备已连接 VID=0x{self.vid:04X} PID=0x{self.pid:04X}",
        )

    @Slot()
    def prepare_walking_capture(self):
        """Keep preflight and the formal passage on the same acquisition stream."""
        self._health_check_active = False
        self._health_owns_capture = False
        self._health_timer.stop()
        if self.dev is None:
            self._emit_state("error", "设备尚未连接")
        elif not self._capturing:
            self._start_capture_stream()

    @Slot()
    def start_capture(self):
        """Start formal acquisition after the user explicitly authorizes it."""
        if self.dev is None:
            self._emit_state("error", "设备尚未连接，无法开始采集。")
            return
        if self._capturing:
            if self._health_check_active and self._health_owns_capture:
                self._health_check_active = False
                self._health_owns_capture = False
                self._health_timer.stop()
            self._emit_state("streaming", "设备正在采集")
            return
        if not self._start_capture_stream():
            return
        self._emit_state("streaming", "设备正在采集")

    def _start_capture_stream(self) -> bool:
        """Start callbacks without deciding how the UI labels the stream."""
        with self._frame_lock:
            self._discard_frames = True
            self._start_ack_pending = False
            self._start_ack.clear()
            self._start_ack_code = None
            self._assembler.reset()
            self.layout = self._assembler.layout
            self._layout_announced = False
        self._pending_bits = None
        self._pending_hex = None
        self._ensure_timer()
        try:
            try:
                self.dev.dll.set_timeout(self.timeout_ms)
            except Exception:
                pass
            if self.capture_command_required:
                # DLL StartCapture already enables the FPGA. Stop it natively
                # before draining; hand-built extra commands do not stop DATA.
                if self.dev.stop_capture() != 0:
                    raise RuntimeError("DLL 无法停止上一轮采集")
                self._discard_startup_input()
            self.dev.set_on_bytes(self._on_bytes)
            self.dev.set_on_frame(self._on_frame)
            if hasattr(self.dev, "set_on_issue"):
                self.dev.set_on_issue(self._on_protocol_issue)
            with self._frame_lock:
                self._discard_frames = bool(self.capture_command_required)
            ret = self.dev.start_auto_read(self.chunk_size, timeout_ms=self.timeout_ms)
            if ret != 0:
                raise RuntimeError(f"start_auto_read 失败: {ret}")
            with self._frame_lock:
                self._start_ack_pending = bool(self.capture_command_required)
            if self.dev.start_capture() != 0:
                raise RuntimeError("DLL 采集启动失败")
            if self.capture_command_required:
                if not self._start_ack.wait(CAPTURE_START_TIMEOUT_S):
                    raise RuntimeError("等待 FPGA 采集启动应答超时，请重新连接设备")
                if self._start_ack_code != 0:
                    raise RuntimeError(f"FPGA 拒绝采集启动，ACK={self._start_ack_code}")
            self._capturing = True
            return True
        except Exception as e:
            self._close_frame_gate()
            self.dev.set_on_frame(None)
            self.dev.set_on_bytes(None)
            self.dev.stop_auto_read()
            self.dev.stop_capture()
            self._capturing = False
            self._emit_state("error", f"启动读取失败: {e}")
            return False

    @Slot()
    def refresh_led_health(self):
        """Collect a small background sample and report only per-LED anomalies."""
        if self.dev is None:
            self.led_health_changed.emit(
                {
                    "status": "insufficient",
                    "sample_count": 0,
                    "disconnected_leds": [],
                    "flickering_leds": [],
                }
            )
            return

        owns_existing_stream = (
            self._health_check_active and self._health_owns_capture
        )
        self._health_frames.clear()
        self._health_filter = BeamDisplayFilter(10)
        self._health_first_sample = None
        self._health_check_active = True
        self._health_deadline = time.perf_counter() + LED_HEALTH_TIMEOUT_S
        self.led_health_changed.emit(
            {
                "status": "checking",
                "sample_count": 0,
                "disconnected_leds": [],
                "flickering_leds": [],
            }
        )
        if not self._capturing:
            if not self._start_capture_stream():
                self._health_check_active = False
                return
            self._health_owns_capture = True
        else:
            self._health_owns_capture = owns_existing_stream
        self._health_timer.start()

    def _record_led_health_frame(self, frame) -> None:
        if not self._health_check_active:
            return
        previous = self._health_filter.last_frame
        invalid = (not all(frame.valid_bits) or frame.dropped_frames_before
                   or any(flag != "all_beams_blocked" for flag in frame.quality_flags))
        if (previous is None or frame.stream_id != previous.stream_id or frame.layout != previous.layout
                or frame.sample_index != previous.sample_index + 1 or invalid):
            self._health_frames.clear()
            self._health_filter = BeamDisplayFilter(10)
            self._health_first_sample = frame.sample_index
        if invalid:
            return
        payload = self._health_filter.feed(frame)
        # Let the initial state settle before classifying its confirmed changes.
        if (frame.sample_index - self._health_first_sample >= self._health_filter.samples
                and len(self._health_frames) < LED_HEALTH_TARGET_FRAMES):
            self._health_frames.append(list(frame.layout.contact_bits(payload)))

    def _poll_led_health(self) -> None:
        if not self._health_check_active:
            self._health_timer.stop()
            return
        if (
            len(self._health_frames) >= LED_HEALTH_TARGET_FRAMES
            or time.perf_counter() >= self._health_deadline
        ):
            self._finish_led_health()

    def _finish_led_health(self) -> None:
        if not self._health_check_active:
            return
        self._health_check_active = False
        self._health_timer.stop()
        result = summarize_led_health(
            self._health_frames,
            self.layout.bit_count if self.layout else 96,
        )
        result["confirmation_ms"] = self._health_filter.samples
        self._health_frames.clear()

        if self._health_owns_capture and self.dev is not None:
            self._close_frame_gate()
            try:
                self.dev.set_on_bytes(None)
                self.dev.set_on_frame(None)
                self.dev.stop_auto_read()
                self.dev.stop_capture()
            except Exception:
                pass
            self._capturing = False
        self._health_owns_capture = False
        self.led_health_changed.emit(result)

    def start(self):
        """Backward-compatible one-shot start for legacy tools."""
        self.connect_device()
        if self.dev is not None:
            self.start_capture()

    @Slot()
    def stop(self):
        self._close_frame_gate()
        self._stop.set()
        self._health_check_active = False
        self._health_owns_capture = False
        self._health_frames.clear()
        self._health_timer.stop()
        if self._flush_timer is not None:
            try:
                self._flush_timer.stop()
            except Exception:
                pass
            self._flush_timer.deleteLater()
            self._flush_timer = None
        # 尝试最后一次刷新
        self._maybe_flush(force=True)
        if self.dev:
            try:
                self.dev.set_on_bytes(None)
            except Exception:
                pass
            try:
                self.dev.set_on_frame(None)
            except Exception:
                pass
            try:
                self.dev.stop_auto_read()
            except Exception:
                pass
            try:
                self.dev.stop_capture()
            except Exception:
                pass
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None
        self._capturing = False
        self._emit_state("disconnected", "设备已断开")
