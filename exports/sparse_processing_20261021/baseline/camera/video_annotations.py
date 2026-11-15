"""Frame annotations and transactional JSON persistence, independent of Qt."""

import json
import math
import os
import tempfile
from pathlib import Path


def angle_degrees(points):
    a, b, c = points
    u = (a[0] - b[0], a[1] - b[1])
    v = (c[0] - b[0], c[1] - b[1])
    if math.hypot(*u) < 1e-8 or math.hypot(*v) < 1e-8:
        raise ValueError("顶点不能与端点重合，请重新选点")
    return math.degrees(math.atan2(abs(u[0] * v[1] - u[1] * v[0]), u[0] * v[0] + u[1] * v[1]))


class VideoAnnotations:
    def __init__(self, video_path, frame_count, width, height):
        self.path = Path(video_path).with_suffix(".annotations.json")
        self.video = {"frame_count": frame_count, "width": width, "height": height}
        self.records = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data["version"] != 1 or data["video"] != self.video:
                    raise ValueError("标注版本或录像帧数、尺寸不匹配")
                self._validate(data["annotations"])
                self.records = data["annotations"]
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"标注文件无法加载：{exc}") from exc

    def _validate(self, records):
        if not isinstance(records, list):
            raise ValueError("标注记录格式错误")
        ids = set()
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"] or record["id"] in ids:
                raise ValueError("标注编号无效")
            ids.add(record["id"])
            if record.get("kind") == "angle":
                self._check_frame(record["frame"])
                points = record["points"]
                if not isinstance(points, list) or len(points) != 3:
                    raise ValueError("角度必须包含三个点")
                for point in points:
                    if not isinstance(point, (list, tuple)) or len(point) != 2:
                        raise ValueError("标注坐标格式错误")
                    for value, limit in zip(point, (self.video["width"], self.video["height"])):
                        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit - 1:
                            raise ValueError("标注坐标超出图像范围")
                angle_degrees(points)
            elif record.get("kind") == "interval":
                self._check_frame(record["start"])
                self._check_frame(record["end"])
                if record["end"] <= record["start"]:
                    raise ValueError("计时终点必须晚于起点")
            else:
                raise ValueError("未知标注类型")

    def _check_frame(self, index):
        if type(index) is not int or not 0 <= index < self.video["frame_count"]:
            raise ValueError("标注帧号超出录像范围")

    def commit(self, records):
        """Publish in memory only after the disk replacement succeeds."""
        self._validate(records)
        data = {"version": 1, "video": self.video, "annotations": records}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=self.path.name + ".", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, allow_nan=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.records = records
