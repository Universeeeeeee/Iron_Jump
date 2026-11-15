"""AVI frame access and optional per-frame capture times (no Qt dependency)."""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoInfo:
    frame_count: int
    fps: float
    times: np.ndarray
    time_source: str
    warning: str = ""


class AviVideo:
    """Owned and accessed by one decoding thread; cache at most eight images."""

    def __init__(self, path: str):
        self._capture = None
        self._cache = OrderedDict()
        self._next_index = 0
        path = Path(path)
        if path.suffix.lower() != ".avi":
            raise ValueError("当前仅支持 AVI 录像")
        self._capture = cv2.VideoCapture(str(path))
        try:
            if not self._capture.isOpened():
                raise ValueError("无法打开 AVI 录像")
            count_value = self._capture.get(cv2.CAP_PROP_FRAME_COUNT)
            if not np.isfinite(count_value) or count_value < 1:
                raise ValueError("录像没有可读取的帧")
            count = int(count_value)
            fps = float(self._capture.get(cv2.CAP_PROP_FPS))
            warning = ""
            try:
                times = np.load(path.with_suffix(".timestamps.npy"), allow_pickle=False)
                if not isinstance(times, np.ndarray):
                    times.close()
                    raise ValueError("时间文件必须是单个数组")
                if (
                    times.dtype != np.float64 or times.ndim != 1 or len(times) != count
                    or not np.all(np.isfinite(times)) or times[0] != 0
                    or not np.all(np.diff(times) > 0)
                ):
                    raise ValueError("时间数据格式、帧数或顺序不符")
                source = "采样时间"
            except (OSError, ValueError, TypeError, EOFError) as exc:
                if not np.isfinite(fps) or fps <= 0:
                    raise ValueError("录像没有有效帧率或逐帧时间数据") from exc
                times = np.arange(count, dtype=np.float64) / fps
                source = "时间按帧率估算"
                warning = "未找到逐帧时间文件" if isinstance(exc, FileNotFoundError) else "逐帧时间文件无效"
            times.setflags(write=False)
            self.info = VideoInfo(count, fps, times, source, warning)
        except Exception:
            self.close()
            raise

    def read(self, index: int) -> np.ndarray:
        if not 0 <= index < self.info.frame_count:
            raise IndexError(index)
        if index in self._cache:
            self._cache.move_to_end(index)
            return self._cache[index]
        if index != self._next_index:
            if not self._capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                raise RuntimeError(f"无法定位第 {index + 1} 帧")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            self._next_index = -1
            raise RuntimeError(f"第 {index + 1} 帧解码失败")
        self._next_index = index + 1
        self._cache[index] = frame
        if len(self._cache) > 8:
            self._cache.popitem(last=False)
        return frame

    def close(self):
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._cache.clear()
