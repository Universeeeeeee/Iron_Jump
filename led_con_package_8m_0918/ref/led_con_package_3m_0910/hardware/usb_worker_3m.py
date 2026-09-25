"""
usb_worker_3m.py — USB 数据采集 Worker (3m扩展版)

修改点 (相对原usb_worker.py):
  <<<3M-1>> _bytes_to_bits: 支持自动检测1m(12B=96bit)/3m(36B=288bit)
  <<<3M-2>> 新增 led_bits_3m_signal: 发射3组96位 (1m/2m/3m各一组)
  <<<3M-3>> _on_frame / _flush_led_if_ready: 根据 payload 长度自动切换模式
  <<<3M-4>> 仅接受精确长度；三米界面指定36字节，通用模式兼容12字节。

数据布局 (3m模式, 36字节/帧，按现场确认的物理段顺序):
  字节 0-11:  2m节点 96bit
  字节 12-23: 3m节点 96bit
  字节 24-35: 1m节点 96bit
  输出信号和数据日志统一归一化为 1m、2m、3m。
"""
from __future__ import annotations

import os
from collections import OrderedDict
import math
import threading
import time

from qtpy.QtCore import QObject, Signal, Slot, QTimer

try:
    from .capture_diagnostics import LatestFrameMailbox
except ImportError:
    from capture_diagnostics import LatestFrameMailbox

try:
    from .receive import CyUsbInterfaceDevice, E_DATA_REPORT
except ImportError:
    try:
        from receive import CyUsbInterfaceDevice, E_DATA_REPORT
    except ImportError:
        CyUsbInterfaceDevice = None
        E_DATA_REPORT = 0x82

try:
    from .protocol import crc8_poly_07
except ImportError:
    try:
        from protocol import crc8_poly_07
    except ImportError:
        def crc8_poly_07(data: bytes) -> int:
            crc = 0x00
            for b in data:
                crc ^= b
                for _ in range(8):
                    if (crc & 0x80) != 0:
                        crc = ((crc << 1) & 0xFF) ^ 0x07
                    else:
                        crc = (crc << 1) & 0xFF
            return crc & 0xFF

FRAME_HEADER = b'\x5A\x5A\x5A\x5A'
FRAME_TAIL = b'\xA5\xA5\xA5\xA5'
CMD_CAPTURE = 0x00


BYTES_PER_NODE = 12
BITS_PER_NODE = 96
NODE_COUNT_3M = 3
BYTES_PER_FRAME_3M = BYTES_PER_NODE * NODE_COUNT_3M
BITS_PER_FRAME_3M = BITS_PER_NODE * NODE_COUNT_3M

LED_HEALTH_TARGET_FRAMES = 64
LED_HEALTH_MIN_FRAMES = 20
LED_HEALTH_TIMEOUT_S = 0.8


def _bytes_to_bits_single(payload: bytes, count: int = BITS_PER_NODE) -> list:
    bits = []
    for b in payload[:count // 8]:
        for i in range(8):
            bits.append((b >> i) & 0x1)
    return bits[:count]


def _bytes_to_bits_3m(payload: bytes) -> list:
    bits = []
    for b in payload[:BYTES_PER_FRAME_3M]:
        for i in range(8):
            bits.append((b >> i) & 0x1)
    return bits[:BITS_PER_FRAME_3M]


def _split_3m(bits_288: list) -> tuple:
    return (
        bits_288[192:288],  # physical 1m is the third wire group
        bits_288[0:96],     # physical 2m is the first wire group
        bits_288[96:192],   # physical 3m is the second wire group
    )


def summarize_led_health(contact_frames: list[list[int]]) -> dict:
    frames = [
        [1 if int(bit) else 0 for bit in frame[:96]]
        for frame in contact_frames
        if len(frame) >= 96
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
    for led_index in range(96):
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
    data_received = Signal(str)
    device_state_changed = Signal(str, str)
    led_bits_signal = Signal(list)
    led_contact_signal = Signal(list)
    raw_contact_signal = Signal(list, float)
    led_bits_3m_signal = Signal(list, list, list)
    led_contact_3m_signal = Signal(list, list, list)
    raw_contact_3m_signal = Signal(list, list, list, float)
    led_health_changed = Signal(dict)

    def __init__(self, dll_path=None, vid=0x04B4, pid=0x1004, timeout_ms=1,
                 chunk_size=512, expected_payload_bytes=None, stability_ms=None,
                 required_dark_bits=(), display_mailbox=None, diagnostics=None):
        super().__init__()
        self.dll_path = dll_path
        self.vid = int(vid)
        self.pid = int(pid)
        self.timeout_ms = int(timeout_ms)
        self.chunk_size = int(chunk_size)
        self.expected_payload_bytes = expected_payload_bytes
        # Wire bit positions of independently confirmed, permanently dark LEDs.
        self.required_dark_bits = tuple(required_dark_bits)
        self.display_mailbox = display_mailbox or LatestFrameMailbox()
        self.diagnostics = diagnostics
        if any(not isinstance(bit, int) or not 0 <= bit < BITS_PER_FRAME_3M
               for bit in self.required_dark_bits):
            raise ValueError("required_dark_bits must contain wire indices 0..287")
        self.rejected_alignment_frames = 0
        # Zero disables temporal filtering for diagnostics/precise short pulses.
        if stability_ms is None:
            stability_ms = os.getenv("DAYU_FRAME_CONFIRM_MS", "10")
        self.stability_interval = max(0.0, float(stability_ms)) / 1000.0
        self._stable_payload = None
        self._candidate_payload = None
        self._candidate_count = 0
        self._candidate_since = 0.0
        self.dev = None
        self._capturing = False
        self._stop = threading.Event()
        self._frames = {}
        self._recent_frames = OrderedDict()
        self._packet_index_base = None
        self._update_lock = threading.RLock()
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
        self._pending_bits_3m = None
        self._flush_timer = None
        self._health_frames: list[list[int]] = []
        self._health_check_active = False
        self._health_owns_capture = False
        self._health_deadline = 0.0
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(50)
        self._health_timer.timeout.connect(self._poll_led_health)

    def _emit(self, msg: str):
        try:
            self.data_received.emit(msg)
        except Exception:
            print(msg)

    def _emit_state(self, state: str, message: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics.log_status("device_state", state=state, message=message)
        self.device_state_changed.emit(state, message)
        self._emit(message)

    def _bytes_to_bits(self, payload: bytes):
        if len(payload) >= BYTES_PER_FRAME_3M:
            return _bytes_to_bits_3m(payload), True
        else:
            return _bytes_to_bits_single(payload[:BYTES_PER_NODE]), False

    def _extract_payload(self, subpack) -> bytes:
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
        try:
            blen = int(getattr(subpack, "bufferLen"))
            if blen != len(raw) or blen <= 0:
                return b""
        except Exception:
            return b""
        return raw

    def _queue_update(self, hex_text=None, bits=None, bits_3m=None):
        with self._update_lock:
            if hex_text:
                self._pending_hex = hex_text
            if bits is not None:
                self._pending_bits = bits
            if bits_3m is not None:
                self._pending_bits_3m = bits_3m
            self._maybe_flush()

    def _maybe_flush(self, force=False):
        with self._update_lock:
            self._flush_pending(force)

    def _flush_pending(self, force=False):
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
                contact_bits = [1 - b for b in bits_to_emit]
                self.led_contact_signal.emit(contact_bits)
            except Exception:
                pass
        if self._pending_bits_3m is not None and (force or self.led_interval == 0.0 or now - self._last_led_ts >= self.led_interval):
            bits_3m = self._pending_bits_3m
            self._pending_bits_3m = None
            self._last_led_ts = now
            try:
                bits_1m, bits_2m, bits_3m_node = _split_3m(bits_3m)
                self.led_bits_3m_signal.emit(bits_1m, bits_2m, bits_3m_node)
                contact_1m = [1 - b for b in bits_1m]
                contact_2m = [1 - b for b in bits_2m]
                contact_3m = [1 - b for b in bits_3m_node]
                self.led_contact_3m_signal.emit(contact_1m, contact_2m, contact_3m)
            except Exception:
                pass

    def _on_flush_timer(self):
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

    def _flush_led_if_ready(self, frameIdx: int):
        node = self._frames.get(frameIdx)
        if not node:
            return
        packs = node.get("packs", {})
        packNum = node.get("packNum", 0)
        if packNum <= 0 or len(packs) < packNum:
            return
        # Select the index base before assembly: fallback must not retain
        # packets already appended by a failed one-based attempt.
        detected_base = 0 if 0 in packs else 1
        base = self._packet_index_base
        if base is None:
            base = detected_base
        indices = range(base, packNum + base)
        if set(packs) != set(indices):
            self._frames.pop(frameIdx, None)
            return
        # A three-node frame consists of three complete 12-byte node packets.
        # Total size alone would allow 11+13+12 and shift every later boundary.
        if self.expected_payload_bytes == 36 and packNum == 3 and any(
            len(packs[i]) != BYTES_PER_NODE for i in indices
        ):
            self._frames.pop(frameIdx, None)
            self._candidate_payload = None
            self._candidate_count = 0
            return
        payload = b"".join(packs[i] for i in indices)
        self._frames.pop(frameIdx, None)
        if self._packet_index_base is None:
            self._packet_index_base = base
        self._complete_frame(frameIdx, payload)

    def _complete_frame(self, frame_idx, payload):
        # No global high-water mark: hardware counter width/restarts need not
        # match the 32-bit transport field. Bound retransmission history by time
        # and count; a single large ID cannot permanently suppress good frames.
        now = time.perf_counter()
        key = (frame_idx, payload)
        for old_key, timestamp in list(self._recent_frames.items()):
            if now - timestamp > 0.1:
                self._recent_frames.pop(old_key, None)
            else:
                break
        if key in self._recent_frames:
            return
        self._recent_frames[key] = now
        if len(self._recent_frames) > 64:
            self._recent_frames.popitem(last=False)
        self._process_payload(payload)

    def _accept_stable_payload(self, payload: bytes, now: float) -> bool:
        """Only forward observed frames; never synthesize or force LED bits.

        Require both elapsed time and repeats: USB reads can deliver many
        duplicate frames in one burst. Known persistent failed LEDs are retained.
        """
        if self.stability_interval == 0.0:
            return True
        if payload == self._stable_payload:
            self._candidate_payload = None
            self._candidate_count = 0
            return True
        if payload != self._candidate_payload:
            self._candidate_payload = payload
            self._candidate_count = 1
            self._candidate_since = now
            return False
        self._candidate_count += 1
        if self._candidate_count < 3 or now - self._candidate_since < self.stability_interval:
            return False
        self._stable_payload = payload
        self._candidate_payload = None
        self._candidate_count = 0
        return True

    def _process_payload(self, payload: bytes):
        # Do not truncate oversized frames or treat a damaged 3m frame as 1m.
        allowed = (self.expected_payload_bytes,) if self.expected_payload_bytes else (12, 36)
        if len(payload) not in allowed or not any(payload):
            if self.diagnostics is not None:
                self.diagnostics.increment("rejected_payloads")
            self._candidate_payload = None
            self._candidate_count = 0
            return
        # Check physical identity before stability confirmation. A shifted frame
        # can repeat indefinitely and must never become the new stable baseline.
        if len(payload) == BYTES_PER_FRAME_3M and any(
            payload[bit // 8] & (1 << (bit % 8)) for bit in self.required_dark_bits
        ):
            self.rejected_alignment_frames += 1
            if self.diagnostics is not None:
                self.diagnostics.increment("rejected_alignment_frames")
            self._candidate_payload = None
            self._candidate_count = 0
            return
        now = time.perf_counter()
        if not self._accept_stable_payload(payload, now):
            return
        bits, is_3m = self._bytes_to_bits(payload)
        if is_3m:
            nodes = _split_3m(bits)
            self.display_mailbox.publish(nodes)
            if self.diagnostics is not None:
                self.diagnostics.record_frame(bytes(nodes[0] + nodes[1] + nodes[2]))
            contacts = tuple([1 - bit for bit in node] for node in nodes)
            self._record_led_health_frame(contacts[0])
            self.raw_contact_3m_signal.emit(*contacts, time.perf_counter())
            normalized = payload[24:36] + payload[0:24]
            self._queue_update(hex_text=normalized.hex(" "), bits_3m=bits)
        else:
            contacts = [1 - bit for bit in bits]
            self._record_led_health_frame(contacts)
            self.raw_contact_signal.emit(contacts, time.perf_counter())
            self._queue_update(hex_text=payload.hex(" "), bits=bits)

    def _on_bytes(self, data: bytes):
        if self.diagnostics is not None:
            self.diagnostics.record_raw(data)
        if not self.debug_raw:
            return
        try:
            head = data[:16].hex(" ")
            self._queue_update(hex_text=f"RAW len={len(data)} head={head}")
        except Exception:
            pass

    def _on_frame(self, frame_type, ack, subpack, status):
        if E_DATA_REPORT is not None and frame_type != E_DATA_REPORT:
            return
        if not subpack:
            return
        try:
            frameIdx = int(subpack.frameIdx)
            packNum = int(subpack.packNum)
            packIdx = int(subpack.packIdx)
        except (AttributeError, TypeError, ValueError):
            return
        if not (0 <= frameIdx <= 0xFFFFFFFF and 1 <= packNum <= 36 and 0 <= packIdx <= packNum):
            return
        payload = self._extract_payload(subpack)
        if not payload or len(payload) > BYTES_PER_FRAME_3M:
            return
        if packNum == 1:
            self._complete_frame(frameIdx, payload)
            return
        now = time.perf_counter()
        # Bound incomplete/invalid frame storage and never combine stale packets.
        for key, value in list(self._frames.items()):
            if now - value["created"] > 1.0:
                self._frames.pop(key, None)
        if frameIdx not in self._frames and len(self._frames) >= 128:
            self._frames.pop(next(iter(self._frames)))
        node = self._frames.setdefault(frameIdx, {
            "packs": {}, "packNum": packNum, "created": now, "invalid": False,
        })
        if node["invalid"]:
            return
        previous = node["packs"].get(packIdx)
        if node["packNum"] != packNum or (previous is not None and previous != payload):
            node["invalid"] = True
            return
        node["packs"][packIdx] = payload
        self._flush_led_if_ready(frameIdx)

    @Slot()
    def connect_device(self):
        self._stop.clear()
        if self.dev is not None:
            self._emit_state("connected", "设备已连接")
            return
        self._emit_state("connecting", "正在连接设备...")
        if CyUsbInterfaceDevice is None:
            self._emit_state("error", "无法导入 receive.CyUsbInterfaceDevice，请检查 receive.py 与 DLL 可用性。")
            return
        try:
            self.dev = CyUsbInterfaceDevice(self.dll_path)
        except Exception as e:
            self.dev = None
            self._emit_state("error", f"加载 DLL 失败: {e}")
            return
        if not self.dev.open(self.vid, self.pid):
            self.dev = None
            self._emit_state("error", f"打开设备失败: VID=0x{self.vid:04X} PID=0x{self.pid:04X}")
            return
        self._emit_state("connected", f"设备已连接 VID=0x{self.vid:04X} PID=0x{self.pid:04X}")

    @Slot()
    def start_capture(self):
        if self.dev is None:
            self._emit_state("error", "设备尚未连接")
            return
        if self._capturing:
            self._emit_state("streaming", "设备正在采集")
            return
        if not self._start_capture_stream():
            return
        self._emit_state("streaming", "设备正在采集")

    def _send_capture_cmd(self, enable: bool) -> bool:
        """<<<FIX-CAP>> 发送FPGA采集使能/停止命令帧
        
        命令帧格式 (usb_ctrl.v协议):
          5A5A5A5A | CMD(1B) | LEN(1B,高4位=para_len) | PARA(para_len字节) | CRC8(1B) | A5A5A5A5
        
        采集使能命令: CMD=0x00, para_len=1, PARA=0x01(使能)/0x00(停止)
        """
        if not self.dev:
            return False
        cmd = CMD_CAPTURE
        len_byte = 0x10  # 高4位=1(para_len=1), 低4位=0
        para = 0x01 if enable else 0x00
        crc = crc8_poly_07(bytes([cmd, len_byte, para]))
        frame = FRAME_HEADER + bytes([cmd, len_byte, para, crc]) + FRAME_TAIL
        try:
            n = self.dev.write(frame, timeout_ms=self.timeout_ms)
            action = "使能" if enable else "停止"
            if n > 0:
                self._emit(f"FPGA采集{action}命令已发送 ({n}字节)")
                return True
            else:
                self._emit(f"FPGA采集{action}命令发送失败 (write返回{n})")
                return False
        except Exception as e:
            self._emit(f"FPGA采集命令发送异常: {e}")
            return False

    def _start_capture_stream(self) -> bool:
        self.rejected_alignment_frames = 0
        self._stable_payload = None
        self._candidate_payload = None
        self._candidate_count = 0
        self._pending_bits = None
        self._pending_bits_3m = None
        self._pending_hex = None
        self._frames.clear()
        self._recent_frames.clear()
        self._packet_index_base = None
        self._ensure_timer()
        try:
            try:
                self.dev.dll.set_timeout(self.timeout_ms)
            except Exception:
                pass
            self.dev.start_capture()
            self.dev.set_on_bytes(self._on_bytes)
            self.dev.set_on_frame(self._on_frame)
            ret = self.dev.start_auto_read(self.chunk_size, timeout_ms=self.timeout_ms)
            if ret != 0:
                self._emit_state("error", f"start_auto_read 失败: {ret}")
                return False
            self._capturing = True
            # <<<FIX-CAP>> 发送FPGA采集使能命令 (capture_en=1)
            # 没有这条命令, FPGA的capture_en=0, 不发送任何数据帧
            self._send_capture_cmd(enable=True)
            return True
        except Exception as e:
            self._capturing = False
            self._emit_state("error", f"启动读取失败: {e}")
            return False

    def _record_led_health_frame(self, contact_bits: list[int]) -> None:
        if not self._health_check_active:
            return
        if len(contact_bits) >= 96 and len(self._health_frames) < LED_HEALTH_TARGET_FRAMES:
            self._health_frames.append(list(contact_bits[:96]))

    def _poll_led_health(self) -> None:
        if not self._health_check_active:
            self._health_timer.stop()
            return
        if len(self._health_frames) >= LED_HEALTH_TARGET_FRAMES or time.perf_counter() >= self._health_deadline:
            self._finish_led_health()

    def _finish_led_health(self) -> None:
        if not self._health_check_active:
            return
        self._health_check_active = False
        self._health_timer.stop()
        result = summarize_led_health(self._health_frames)
        self._health_frames.clear()
        if self._health_owns_capture and self.dev is not None:
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
        if self.diagnostics is not None:
            self.diagnostics.start()
            self.diagnostics.log_status(
                "capture_starting", timeout_ms=self.timeout_ms,
                chunk_size=self.chunk_size,
                expected_payload_bytes=self.expected_payload_bytes)
        self.connect_device()
        if self.dev is not None:
            self.start_capture()

    def stop(self):
        if self.diagnostics is not None:
            self.diagnostics.log_status("capture_stopping")
        self._stop.set()
        # <<<FIX-CAP>> 发送FPGA采集停止命令 (capture_en=0)
        if self.dev and self._capturing:
            try:
                self._send_capture_cmd(enable=False)
            except Exception:
                pass
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
        if self.diagnostics is not None:
            self.diagnostics.stop()
