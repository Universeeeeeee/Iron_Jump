"""Random access reader for TinySE's raw MJPEG plus CSV index."""

from __future__ import annotations

import csv
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class MjpgFrame:
    record_frame_index: int
    capture_frame_index: int
    sample_time_s: float
    record_elapsed_seconds: float
    offset: int
    length: int


class MjpgIndexedVideo:
    def __init__(self, video_path: str | Path, index_path: str | Path) -> None:
        self.video_path = Path(video_path)
        self.index_path = Path(index_path)
        self.frames = self._read_index()
        self._times = [frame.sample_time_s for frame in self.frames]

    def _read_index(self) -> list[MjpgFrame]:
        with self.index_path.open(newline="", encoding="utf-8-sig") as file:
            return [
                MjpgFrame(
                    int(row.get("record_frame_index", index)),
                    int(row.get("capture_frame_index", index)),
                    float(row["sample_time"]),
                    float(row.get("record_elapsed_seconds", 0.0)),
                    int(row["offset"]),
                    int(row["length"]),
                )
                for index, row in enumerate(csv.DictReader(file))
            ]

    def nearest_index(self, sample_time_s: float) -> int | None:
        if not self.frames:
            return None
        index = bisect_left(self._times, sample_time_s)
        if index <= 0:
            return 0
        if index >= len(self.frames):
            return len(self.frames) - 1
        before = index - 1
        return before if sample_time_s - self._times[before] <= self._times[index] - sample_time_s else index

    def read(self, index: int):
        frame_meta = self.frames[index]
        with self.video_path.open("rb") as file:
            file.seek(frame_meta.offset)
            data = file.read(frame_meta.length)
        return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)

    def read_nearest(self, sample_time_s: float):
        index = self.nearest_index(sample_time_s)
        return (None, None) if index is None else (self.read(index), self.frames[index])

    def iter_time_window(self, start_s: float, end_s: float):
        if not self.frames:
            return
        start = max(0, bisect_left(self._times, start_s) - 1)
        for index in range(start, len(self.frames)):
            frame = self.frames[index]
            if frame.sample_time_s > end_s:
                break
            if frame.sample_time_s >= start_s:
                yield index, frame


__all__ = ["MjpgFrame", "MjpgIndexedVideo"]
