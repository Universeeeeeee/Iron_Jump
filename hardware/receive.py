from __future__ import annotations

import argparse
import ctypes
import os
import threading
from typing import Callable, Optional, Tuple
import re

# Local protocol parser
try:
    from .protocol import (
        ProtocolParser,
        E_ACK,
        E_STATUS_REPORT,
        E_DATA_REPORT,
        FRAME_HEADER_FLAG,
        FRAME_TAIL_FLAG,
        crc8_poly_07,
    )
except Exception:  # running as script
    from protocol import (
        ProtocolParser,
        E_ACK,
        E_STATUS_REPORT,
        E_DATA_REPORT,
        FRAME_HEADER_FLAG,
        FRAME_TAIL_FLAG,
        crc8_poly_07,
    )


class Cy68013DLL:
    """
    Thin ctypes wrapper for cy68013_xxx exported functions (stdcall) from the provided DLL.

    Usage:
      dll = Cy68013DLL("path/to/cy68013.dll")  # or None to search in PATH/current dir
      dev = dll.open(vid, pid)
      dll.start_auto_read(dev, chunk_size, cb, user)
      ...
      dll.stop_auto_read(dev)
      dll.close(dev)
    """


# ===== New DLL: CyUsbInterface.dll (extern "C" stdcall exports) =====
class CyUsbInterfaceDLL:
    """
    ctypes wrapper for CyUsbInterface.dll extern "C" stdcall exports.
    Exposed functions:
      - InitDevice(USHORT vid, USHORT pid) -> bool
      - CloseDevice() -> void
      - SetTimeout(ULONG timeoutMs) -> void
      - ReadDevice(uint8_t* buf, int len) -> int
      - WriteDevice(const uint8_t* buf, int len) -> int
      - StartCapture()/StopCapture() -> bool
      - IsDeviceConnected() -> bool
      - GetVendorId()/GetProductId() -> unsigned short
      - GetDeviceCount() -> int
      - GetLastErrorText() -> const char*
      - IsEndpointReady(int endpointType) -> bool  (0:IN, 1:OUT)
      - ResetDevice() -> bool
      - FlushInputBuffer() -> unsigned long
      - SendCommandFrame(unsigned char cmdType) -> bool
      - BytesAvailable() -> int
    """

    def __init__(self, dll_path: Optional[str] = None):
        self._lib = self._load_dll(dll_path)
        self._set_prototypes()

    @staticmethod
    def _load_dll(dll_path: Optional[str]):
        candidates = []
        if dll_path:
            candidates.append(dll_path)
        candidates.extend([
            "CyUsbInterface.dll",
            "cyusbinteface.dll",
            "dll.dll",  # allow generic name
        ])
        last_err = None
        for p in candidates:
            try:
                return ctypes.WinDLL(p)
            except OSError as e:
                last_err = e
        raise OSError(f"Failed to load CyUsbInterface DLL. Tried: {candidates}. Last error: {last_err}")

    def _set_prototypes(self):
        lib = self._lib

        def _bind(name: str, restype, argtypes, stdcall_bytes: Optional[int] = None):
            candidates = [name]
            if stdcall_bytes:
                candidates += [f"_{name}", f"{name}@{stdcall_bytes}", f"_{name}@{stdcall_bytes}"]
            last = None
            fn = None
            for nm in candidates:
                try:
                    fn = getattr(lib, nm)
                    break
                except AttributeError as e:
                    last = e
            if fn is None:
                raise AttributeError(f"Function '{name}' not found in CyUsbInterface DLL. Tried: {candidates}") from last
            fn.restype = restype
            fn.argtypes = argtypes
            setattr(lib, name, fn)

        US = ctypes.c_ushort
        UL = ctypes.c_ulong
        I = ctypes.c_int
        UBYTE_P = ctypes.POINTER(ctypes.c_ubyte)

        ptr32 = (ctypes.sizeof(ctypes.c_void_p) == 4)
        # Argument byte counts for stdcall decoration (32-bit only)
        SB = lambda *sizes: sum(sizes) if ptr32 else None

        _bind("InitDevice", ctypes.c_bool, [US, US], stdcall_bytes=SB(2, 2))
        _bind("CloseDevice", None, [], stdcall_bytes=SB())
        _bind("SetTimeout", None, [UL], stdcall_bytes=SB(4))
        _bind("ReadDevice", I, [UBYTE_P, I], stdcall_bytes=SB(4, 4))
        _bind("WriteDevice", I, [UBYTE_P, I], stdcall_bytes=SB(4, 4))
        _bind("StartCapture", ctypes.c_bool, [], stdcall_bytes=SB())
        _bind("StopCapture", ctypes.c_bool, [], stdcall_bytes=SB())
        _bind("IsDeviceConnected", ctypes.c_bool, [], stdcall_bytes=SB())
        _bind("GetVendorId", US, [], stdcall_bytes=SB())
        _bind("GetProductId", US, [], stdcall_bytes=SB())
        _bind("GetDeviceCount", I, [], stdcall_bytes=SB())
        _bind("GetLastErrorText", ctypes.c_char_p, [], stdcall_bytes=SB())
        _bind("IsEndpointReady", ctypes.c_bool, [I], stdcall_bytes=SB(4))
        _bind("ResetDevice", ctypes.c_bool, [], stdcall_bytes=SB())
        _bind("FlushInputBuffer", ctypes.c_ulong, [], stdcall_bytes=SB())
        _bind("SendCommandFrame", ctypes.c_bool, [ctypes.c_ubyte], stdcall_bytes=SB(4))
        _bind("BytesAvailable", I, [], stdcall_bytes=SB())

    # ---- Raw wrappers ----
    def init(self, vid: int, pid: int) -> bool:
        return bool(self._lib.InitDevice(vid & 0xFFFF, pid & 0xFFFF))

    def close(self) -> None:
        self._lib.CloseDevice()

    def set_timeout(self, ms: int) -> None:
        self._lib.SetTimeout(ctypes.c_ulong(int(ms)))

    def is_connected(self) -> bool:
        return bool(self._lib.IsDeviceConnected())

    def vendor_id(self) -> int:
        return int(self._lib.GetVendorId())

    def product_id(self) -> int:
        return int(self._lib.GetProductId())

    def get_device_count(self) -> int:
        return int(self._lib.GetDeviceCount())

    def get_last_error(self) -> str:
        p = self._lib.GetLastErrorText()
        try:
            return p.decode(errors="ignore") if isinstance(p, (bytes, bytearray)) else (p or b"").decode(errors="ignore")
        except Exception:
            return ""

    def is_endpoint_ready(self, endpoint_type: int) -> bool:
        return bool(self._lib.IsEndpointReady(int(endpoint_type)))

    def reset_device(self) -> bool:
        return bool(self._lib.ResetDevice())

    def flush_input(self) -> int:
        return int(self._lib.FlushInputBuffer())

    def send_command_frame(self, cmd: int) -> bool:
        return bool(self._lib.SendCommandFrame(ctypes.c_ubyte(cmd & 0xFF)))

    def bytes_available(self) -> int:
        return int(self._lib.BytesAvailable())

    def read(self, size: int) -> bytes:
        buf = (ctypes.c_ubyte * int(size))()
        n = int(self._lib.ReadDevice(buf, int(size)))
        if n <= 0:
            return b""
        return bytes(buf[:n])

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        n = int(self._lib.WriteDevice(buf, len(data)))
        return n

    def start_capture(self) -> bool:
        return bool(self._lib.StartCapture())

    def stop_capture(self) -> bool:
        return bool(self._lib.StopCapture())


class CyUsbInterfaceDevice:
    """
    High-level wrapper around CyUsbInterfaceDLL, emulating the same public surface as Cy68013Device
    where reasonable: open/close/is_open, start/stop_capture, read/write, start_auto_read with
    a Python background thread (since this DLL doesn't expose a callback).
    """

    def __init__(self, dll_path: Optional[str] = None):
        self.dll = CyUsbInterfaceDLL(dll_path)
        self._opened = False
        self._timeout_ms = 1000  # used for sync ops and the reader loop
        self._on_bytes: Optional[Callable[[bytes], None]] = None
        self._on_frame: Optional[Callable[[int, object, object, object], None]] = None
        self._rx_buf = bytearray()
        self._lock = threading.Lock()
        self._parser = ProtocolParser(
            frame_index_byteorder=os.getenv("DAYU_FRAME_INDEX_BYTEORDER", "little")
        )
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._vid = None
        self._pid = None

    # ---- Public API (compatible subset) ----
    def open(self, vid: int, pid: int) -> bool:
        ok = self.dll.init(vid, pid)
        self._opened = bool(ok)
        self._vid, self._pid = vid, pid
        if ok:
            # set a default timeout for sync operations
            try:
                self.dll.set_timeout(self._timeout_ms)
            except Exception:
                pass
        return bool(ok)

    def is_open(self) -> bool:
        try:
            return self._opened and self.dll.is_connected()
        except Exception:
            return self._opened

    def close(self):
        try:
            self.stop_auto_read()
        except Exception:
            pass
        try:
            self.dll.close()
        finally:
            self._opened = False

    def start_capture(self) -> int:
        try:
            return 0 if self.dll.start_capture() else -1
        except Exception:
            return -1

    def stop_capture(self) -> int:
        try:
            return 0 if self.dll.stop_capture() else -1
        except Exception:
            return -1

    def get_friendly_name(self) -> str:
        if self._vid is not None and self._pid is not None:
            return f"CyUsbInterface[{self._vid}:{self._pid}]"
        return "CyUsbInterface"

    def set_on_bytes(self, cb: Optional[Callable[[bytes], None]]):
        self._on_bytes = cb

    def set_on_frame(self, cb: Optional[Callable[[int, object, object, object], None]]):
        self._on_frame = cb

    def write(self, data: bytes, timeout_ms: int = 1000) -> int:
        # Update timeout if changed
        if timeout_ms != self._timeout_ms:
            try:
                self.dll.set_timeout(timeout_ms)
                self._timeout_ms = timeout_ms
            except Exception:
                pass
        return int(self.dll.write(data))

    def read(self, size: int, timeout_ms: int = 1000) -> bytes:
        if timeout_ms != self._timeout_ms:
            try:
                self.dll.set_timeout(timeout_ms)
                self._timeout_ms = timeout_ms
            except Exception:
                pass
        return self.dll.read(size)

    def start_auto_read(self, chunk_size: int = 2048, timeout_ms: int | None = None) -> int:
        if self._reader_thread and self._reader_thread.is_alive():
            return 0
        self._stop_evt.clear()
        self._rx_buf.clear()
        if timeout_ms is not None:
            self._timeout_ms = timeout_ms

        def _loop():
            # Use a moderate timeout for responsiveness
            try:
                # honor configured timeout instead of hard-coded 100ms
                self.dll.set_timeout(self._timeout_ms)
            except Exception:
                pass
            while not self._stop_evt.is_set():
                try:
                    avail = 0
                    try:
                        avail = max(0, self.dll.bytes_available())
                    except Exception:
                        pass
                    to_read = min(max(avail, 0) or chunk_size, chunk_size)
                    data = self.dll.read(to_read)
                    if not data:
                        continue
                    if self._on_bytes:
                        try:
                            self._on_bytes(data)
                        except Exception:
                            pass
                    with self._lock:
                        self._rx_buf.extend(data)
                        while True:
                            ret, frame_type, ack, subpack, status = self._parser.parse(self._rx_buf)
                            if ret == 0:
                                if self._on_frame:
                                    try:
                                        self._on_frame(frame_type, ack, subpack, status)
                                    except Exception:
                                        pass
                            else:
                                break
                except Exception:
                    # Swallow to keep thread alive; could add backoff if needed
                    pass

        self._reader_thread = threading.Thread(target=_loop, name="CyUsbInterfaceReader", daemon=False)
        self._reader_thread.start()
        return 0

    def stop_auto_read(self):
        if self._reader_thread and self._reader_thread.is_alive():
            self._stop_evt.set()
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None


if __name__ == "__main__":
    import time
    import sys

    parser = argparse.ArgumentParser(description="USB receive/print utility")
    parser.add_argument(
        "--duration",
        type=float,
        default=float(os.getenv("DAYU_DURATION", "0") or 0.0),
        help="Run for N seconds then stop automatically (0 = until Ctrl+C)",
    )
    args = parser.parse_args()
    duration = max(0.0, float(args.duration or 0.0))

    # 一键运行，无需命令行参数
    # 默认配置（可被环境变量覆盖）
    DLL_PATH = os.getenv("DAYU_DLL", "")
    if not DLL_PATH:
        try:
            # path_utils 位于项目根目录，需要将父目录加入 sys.path
            _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _project_root not in sys.path:
                sys.path.insert(0, _project_root)
            from path_utils import find_dll
            DLL_PATH = find_dll()
        except ImportError:
            DLL_PATH = "CyUsbInterface.dll"
    # 允许十六进制/十进制，两者都兼容
    def _parse_int(env_name: str, default: int) -> int:
        v = os.getenv(env_name)
        if not v:
            return default
        try:
            return int(v, 0)  # 支持 '0x1234' 或 '4660'
        except Exception:
            return default

    VID = _parse_int("DAYU_VID", 0x04B4)
    PID = _parse_int("DAYU_PID", 0x1004)
    READ_TIMEOUT_MS = _parse_int("DAYU_TIMEOUT", 200)
    CHUNK_SIZE = _parse_int("DAYU_CHUNK", 2048)

    # 加载并打开设备（固定使用 CyUsbInterface.dll）
    try:
        probe = ctypes.WinDLL(DLL_PATH)
        getattr(probe, "InitDevice")
        dev = CyUsbInterfaceDevice(DLL_PATH)
        print(f"Loaded DLL: {DLL_PATH} (flavor: CyUsbInterface)")
        print(f"Config: VID=0x{VID:04X} PID=0x{PID:04X} TIMEOUT={READ_TIMEOUT_MS}ms CHUNK={CHUNK_SIZE}")
    except Exception as e:
        print("Failed to load CyUsbInterface DLL:", e)
        sys.exit(1)

    if not dev.open(VID, PID):
        print("Open failed. 请检查设备连接、VID/PID、驱动安装以及 Python 与 DLL 位数匹配。")
        sys.exit(1)

    print("Device:", dev.get_friendly_name())
    try:
        print(f"DeviceCount={dev.dll.get_device_count()} VID=0x{dev.dll.vendor_id():04X} PID=0x{dev.dll.product_id():04X}")
        print(f"EndpointReady IN={dev.dll.is_endpoint_ready(0)} OUT={dev.dll.is_endpoint_ready(1)} BytesAvailable={dev.dll.bytes_available()}")
    except Exception:
        pass

    # 初始化：设置超时、尝试复位与启动命令（若固件忽略也无妨）
    try:
        dev.dll.set_timeout(READ_TIMEOUT_MS)
    except Exception:
        pass
    try:
        dev.dll.reset_device()
    except Exception:
        pass
    try:
        dev.dll.send_command_frame(0x01)
        dev.dll.send_command_frame(0x02)
    except Exception:
        pass

    # 回调：原始数据与解析帧
    def _on_bytes(data: bytes):
        print(f"RAW len={len(data)} hex={data.hex(' ')}")

    def _on_frame(frame_type, ack, subpack, status):
        if frame_type == E_ACK and ack:
            print(f"ACK frame: ACK={ack.ACK}")
        elif frame_type == E_STATUS_REPORT and status:
            print(f"STATUS frame: type={status.type}, value={status.value}")
        elif frame_type == E_DATA_REPORT and subpack:
            payload = getattr(subpack, "body", None)
            try:
                payload_bytes = bytes(payload) if payload is not None else b""
            except Exception:
                payload_bytes = b""
            print(
                f"DATA frame: frameIdx=0x{subpack.frameIdx:08X}, packIdx={subpack.packIdx + 1}/{subpack.packNum}, "
                f"body_len={len(payload_bytes)} hex={payload_bytes.hex(' ')}"
            )
        else:
            print("UNKNOWN frame")

    dev.set_on_bytes(_on_bytes)
    dev.set_on_frame(_on_frame)

    cap_ret = dev.start_capture()
    print("start_capture ret:", cap_ret)
    ret = dev.start_auto_read(CHUNK_SIZE)
    if ret != 0:
        print("start_auto_read failed:", ret)
        dev.close()
        sys.exit(1)

    if duration > 0:
        print(f"Running for up to {duration:.2f}s… 按 Ctrl+C 可提前停止")
    else:
        print("Running... 按 Ctrl+C 停止")
    start_time = time.time()
    sleep_interval = 0.1 if duration > 0 else 1.0
    try:
        while True:
            if duration > 0 and time.time() - start_time >= duration:
                print("\nDuration reached, stopping…")
                break
            time.sleep(sleep_interval)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        try:
            dev.set_on_bytes(None)
            dev.set_on_frame(None)
        except Exception:
            pass
        try:
            dev.stop_auto_read()
        except Exception:
            pass
        try:
            dev.stop_capture()
        except Exception:
            pass
        try:
            dev.close()
        except Exception:
            pass
        print("Done.")
        # 确保正常退出返回码为 0
        sys.exit(0)
