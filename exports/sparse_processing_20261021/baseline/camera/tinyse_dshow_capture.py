from __future__ import annotations

import argparse
import ctypes
import time
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "bin"
RELEASE_DLL = BIN_DIR / "tinyse_capture.dll"
FALLBACK_RELEASE_DLL = BIN_DIR / "tinyse_capture_v2.dll"
DEFAULT_DLL = FALLBACK_RELEASE_DLL if FALLBACK_RELEASE_DLL.exists() else RELEASE_DLL


class TinySeCaptureStats(ctypes.Structure):
    _fields_ = [
        ("requested_width", ctypes.c_int32),
        ("requested_height", ctypes.c_int32),
        ("requested_fps", ctypes.c_int32),
        ("connected_width", ctypes.c_int32),
        ("connected_height", ctypes.c_int32),
        ("connected_fps", ctypes.c_int32),
        ("connected_subtype", ctypes.c_uint32),
        ("connected_avg_time", ctypes.c_int64),
        ("frames", ctypes.c_int64),
        ("wall_fps", ctypes.c_double),
        ("sample_fps", ctypes.c_double),
        ("last_hresult", ctypes.c_int32),
        ("running", ctypes.c_int32),
    ]


class TinySeRecordingStats(ctypes.Structure):
    _fields_ = [
        ("frames_written", ctypes.c_int64),
        ("bytes_written", ctypes.c_int64),
        ("frames_dropped", ctypes.c_int64),
        ("queue_high_watermark_frames", ctypes.c_int64),
        ("queue_high_watermark_bytes", ctypes.c_int64),
        ("queued_frames", ctypes.c_int64),
        ("queued_bytes", ctypes.c_int64),
        ("recording", ctypes.c_int32),
        ("last_hresult", ctypes.c_int32),
    ]


FrameCallback = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    None,
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_int32,
    ctypes.c_int64,
    ctypes.c_double,
    ctypes.c_void_p,
)


def _deliver_frame(
    data,
    length: int,
    frame_index: int,
    sample_time_s: float,
    *,
    on_frame: Callable[[bytes, int, float], None] | None,
    on_timed_frame: Callable[[bytes, int, float, float], None] | None,
) -> None:
    callback_time_s = time.perf_counter()
    copied = ctypes.string_at(data, length)
    if on_timed_frame is not None:
        on_timed_frame(copied, int(frame_index), float(sample_time_s), callback_time_s)
    if on_frame is not None:
        on_frame(copied, int(frame_index), float(sample_time_s))


def _fourcc_text(value: int) -> str:
    if value == 0:
        return "unknown"
    raw = int(value).to_bytes(4, "little", signed=False)
    return raw.decode("ascii", errors="replace")


class TinySeDShowCapture:
    def __init__(
        self,
        device_needle: str = "OBSBOT Tiny SE",
        width: int = 1920,
        height: int = 1080,
        fps: int = 100,
        dll_path: str | Path = DEFAULT_DLL,
        on_frame: Callable[[bytes, int, float], None] | None = None,
        on_timed_frame: Callable[[bytes, int, float, float], None] | None = None,
    ) -> None:
        self.dll_path = Path(dll_path)
        if not self.dll_path.exists():
            raise FileNotFoundError(f"DirectShow capture DLL not found: {self.dll_path}")

        self._dll = ctypes.CDLL(str(self.dll_path))
        self._bind_api()
        self._callback_ref = None
        self._record_paths: tuple[Path, Path] | None = None
        callback_arg = FrameCallback()
        if on_frame is not None or on_timed_frame is not None:
            self._callback_ref = FrameCallback(
                lambda data, length, frame_index, sample_time, user: _deliver_frame(
                    data,
                    length,
                    frame_index,
                    sample_time,
                    on_frame=on_frame,
                    on_timed_frame=on_timed_frame,
                )
            )
            callback_arg = self._callback_ref

        self._started = False
        self._handle = self._dll.tinyse_capture_create(
            device_needle,
            int(width),
            int(height),
            int(fps),
            callback_arg,
            None,
        )
        if not self._handle:
            raise RuntimeError("tinyse_capture_create failed")

    def _bind_api(self) -> None:
        self._dll.tinyse_capture_create.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int32,
            ctypes.c_int32,
            ctypes.c_int32,
            FrameCallback,
            ctypes.c_void_p,
        ]
        self._dll.tinyse_capture_create.restype = ctypes.c_void_p
        self._dll.tinyse_capture_start.argtypes = [ctypes.c_void_p]
        self._dll.tinyse_capture_start.restype = ctypes.c_int32
        self._dll.tinyse_capture_stop.argtypes = [ctypes.c_void_p]
        self._dll.tinyse_capture_stop.restype = ctypes.c_int32
        self._dll.tinyse_capture_destroy.argtypes = [ctypes.c_void_p]
        self._dll.tinyse_capture_destroy.restype = None
        self._dll.tinyse_capture_get_stats.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(TinySeCaptureStats),
        ]
        self._dll.tinyse_capture_get_stats.restype = ctypes.c_int32
        self._dll.tinyse_capture_start_record.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
        ]
        self._dll.tinyse_capture_start_record.restype = ctypes.c_int32
        self._dll.tinyse_capture_stop_record.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(TinySeRecordingStats),
        ]
        self._dll.tinyse_capture_stop_record.restype = ctypes.c_int32
        self._dll.tinyse_capture_get_record_stats.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(TinySeRecordingStats),
        ]
        self._dll.tinyse_capture_get_record_stats.restype = ctypes.c_int32
        self._dll.tinyse_capture_last_error.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_int32,
        ]
        self._dll.tinyse_capture_last_error.restype = ctypes.c_int32

    def start(self) -> None:
        ret = self._dll.tinyse_capture_start(self._handle)
        if ret != 0:
            message = self.last_error() or f"tinyse_capture_start failed: {ret}"
            try:
                stats = self.stats()
                message = f"{message} (hr=0x{stats.last_hresult & 0xFFFFFFFF:08X})"
            except RuntimeError:
                pass
            raise RuntimeError(message)
        self._started = True

    def stop(self) -> None:
        if self._started:
            try:
                self._dll.tinyse_capture_stop(self._handle)
            finally:
                self._started = False

    def close(self) -> None:
        handle = self._handle
        if handle is not None:
            try:
                self.stop()
            except Exception:
                pass
            self._handle = None
            self._dll.tinyse_capture_destroy(handle)

    def stats(self) -> TinySeCaptureStats:
        stats = TinySeCaptureStats()
        ret = self._dll.tinyse_capture_get_stats(self._handle, ctypes.byref(stats))
        if ret != 0:
            raise RuntimeError(f"tinyse_capture_get_stats failed: {ret}")
        return stats

    def start_record(self, stem: str | Path | None = None) -> tuple[Path, Path]:
        if stem is None:
            out_dir = ROOT / "recordings"
            out_dir.mkdir(exist_ok=True)
            stem_path = out_dir / f"tinyse_{time.strftime('%Y%m%d_%H%M%S')}"
        else:
            stem_path = Path(stem)
            if stem_path.suffix:
                stem_path = stem_path.with_suffix("")
            stem_path.parent.mkdir(parents=True, exist_ok=True)

        ret = self._dll.tinyse_capture_start_record(self._handle, str(stem_path))
        if ret != 0:
            message = self.last_error() or f"tinyse_capture_start_record failed: {ret}"
            stats = self.record_stats()
            raise RuntimeError(f"{message} (hr=0x{stats.last_hresult & 0xFFFFFFFF:08X})")

        self._record_paths = (stem_path.with_suffix(".mjpg"), stem_path.with_suffix(".csv"))
        return self._record_paths

    def stop_record(self) -> TinySeRecordingStats:
        stats = TinySeRecordingStats()
        ret = self._dll.tinyse_capture_stop_record(self._handle, ctypes.byref(stats))
        if ret != 0:
            raise RuntimeError(f"tinyse_capture_stop_record failed: {ret}")
        return stats

    def record_stats(self) -> TinySeRecordingStats:
        stats = TinySeRecordingStats()
        ret = self._dll.tinyse_capture_get_record_stats(self._handle, ctypes.byref(stats))
        if ret != 0:
            raise RuntimeError(f"tinyse_capture_get_record_stats failed: {ret}")
        return stats

    def last_error(self) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        ret = self._dll.tinyse_capture_last_error(self._handle, buffer, len(buffer))
        return buffer.value if ret >= 0 else ""

    def __enter__(self) -> "TinySeDShowCapture":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _print_stats(stats: TinySeCaptureStats) -> None:
    print(
        "requested="
        f"{stats.requested_width}x{stats.requested_height}@{stats.requested_fps} "
        "connected="
        f"{stats.connected_width}x{stats.connected_height}@{stats.connected_fps} "
        f"{_fourcc_text(stats.connected_subtype)} "
        f"frames={stats.frames} "
        f"wall_fps={stats.wall_fps:.2f} "
        f"sample_fps={stats.sample_fps:.2f} "
        f"running={stats.running}"
    )


def _print_record_stats(stats: TinySeRecordingStats) -> None:
    print(
        "record="
        f"frames_written={stats.frames_written} "
        f"bytes={stats.bytes_written} "
        f"dropped={stats.frames_dropped} "
        f"queued={stats.queued_frames}/{stats.queued_bytes} "
        f"high_water={stats.queue_high_watermark_frames}/{stats.queue_high_watermark_bytes} "
        f"recording={stats.recording}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Tiny SE DirectShow capture smoke test")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--needle", default="OBSBOT Tiny SE")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=100)
    parser.add_argument("--dll", default=str(DEFAULT_DLL))
    parser.add_argument("--save-first", action="store_true")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--record-stem", default=None)
    args = parser.parse_args()

    first_frame = {"saved": False}

    def on_frame(data: bytes, frame_index: int, sample_time: float) -> None:
        if not args.save_first or first_frame["saved"]:
            return
        out_dir = ROOT / "recordings"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"tinyse_first_mjpg_{int(time.time())}.jpg"
        out_path.write_bytes(data)
        first_frame["saved"] = True
        print(f"saved first compressed frame: {out_path} frame={frame_index} sample_time={sample_time:.3f}")

    callback = on_frame if args.save_first else None
    with TinySeDShowCapture(
        device_needle=args.needle,
        width=args.width,
        height=args.height,
        fps=args.fps,
        dll_path=args.dll,
        on_frame=callback,
    ) as capture:
        capture.start()
        if args.record:
            mjpg_path, csv_path = capture.start_record(args.record_stem)
            print(f"recording raw MJPEG: {mjpg_path}")
            print(f"recording index CSV: {csv_path}")
        deadline = time.perf_counter() + args.seconds
        while time.perf_counter() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.perf_counter())))
            _print_stats(capture.stats())
            if args.record:
                _print_record_stats(capture.record_stats())
        if args.record:
            record_stats = capture.stop_record()
            _print_record_stats(record_stats)
        capture.stop()
        _print_stats(capture.stats())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
