"""
离线步态数据解析器 - 从 .npz 文件读取原始数据并进行步态分析

Usage::

    python single_foot_tracker.py --file gait_capture_20251222_095500.npz

本脚本复用 cluster_test.py 中的 SingleFootDetector 检测框架，
将输入源从硬件改为 .npz 文件中的原始字节流。

数据来源：data_source.py 录制的 .npz 文件，包含：
  - raw: uint8 一维数组（原始字节流）
  - meta: JSON 字符串（采集配置与元数据）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable, Generator, Iterable, List, Optional, Sequence

import numpy as np

# 复用协议解析器
try:
    from .protocol import (
        ProtocolParser,
        E_DATA_REPORT,
        protocol_parser,
    )
except Exception:
    try:
        from hardware.protocol import (
            ProtocolParser,
            E_DATA_REPORT,
            protocol_parser,
        )
    except Exception:
        ProtocolParser = None  # type: ignore
        E_DATA_REPORT = 0x82
        protocol_parser = None  # type: ignore


# ===================== 数据结构（与 cluster_test.py 一致）=====================

COLS = 96
SPACING_CM = 1.04


@dataclass
class LedFrame:
    """原始 LED 帧"""
    timestamp: float
    bits: Sequence[int]  # 1 表示遮挡/触地


@dataclass
class Cluster:
    """连续遮挡段"""
    start: int
    end: int
    length: int
    centroid_idx: float
    centroid_cm: float
    ratio: float


@dataclass
class FootEvent:
    """步态事件"""
    kind: str  # "touch" 或 "lift"
    time: float
    ratio: float
    centroid_cm: Optional[float]
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetectorQualityNotice:
    """不构成 touch/lift 的检测质量事件。"""

    kind: str
    time: float
    cluster_length: int
    ratio: float


# ===================== 检测器（与 cluster_test.py 一致）=====================

class SingleFootDetector:
    """单足触地/腾空检测状态机"""

    def __init__(
        self,
        cols: int = COLS,
        spacing_cm: float = SPACING_CM,
        gap_threshold: int = 1,
        touch_ratio_threshold: float = 0.05,
        lift_ratio_threshold: float = 0.05,
        confirm_samples: int = 10,
        touch_min_cluster_length: int = 4,
        touch_max_cluster_length: int = 50,
    ) -> None:
        self.cols = cols
        self.spacing_cm = spacing_cm
        self.gap_threshold = gap_threshold
        self.touch_ratio_threshold = touch_ratio_threshold
        self.lift_ratio_threshold = lift_ratio_threshold
        self.confirm_samples = confirm_samples
        self.touch_min_cluster_length = touch_min_cluster_length
        self.touch_max_cluster_length = touch_max_cluster_length
        self._reset_state()

    def process(self, frames: Sequence[LedFrame]) -> List[FootEvent]:
        """批量处理多帧"""
        self.reset()
        events: List[FootEvent] = []
        for frame in frames:
            events.extend(self.consume(frame))
        return events

    def consume(self, frame: LedFrame) -> List[FootEvent]:
        """逐帧处理"""
        if self._prev_time is None:
            self._prev_time = frame.timestamp
        return self._process_frame(frame)

    def reset(self) -> None:
        self._reset_state()

    def begin_resync(self) -> None:
        """丢弃跨暂停的转换语义，等待稳定帧只建立基线。"""
        self._state = "resync"
        self._touch_streak = 0
        self._lift_streak = 0
        self._resync_ground_streak = 0
        self._resync_air_streak = 0
        self._prev_time = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_primary_cluster(self) -> Optional[Cluster]:
        return self._last_primary_cluster

    def pop_quality_notices(self) -> List[DetectorQualityNotice]:
        notices = list(self._quality_notices)
        self._quality_notices.clear()
        return notices

    def _reset_state(self) -> None:
        self._state = "air"
        self._touch_streak = 0
        self._lift_streak = 0
        self._prev_ratio = 0.0
        self._prev_time: Optional[float] = None
        self._last_primary_cluster: Optional[Cluster] = None
        self._quality_notices: List[DetectorQualityNotice] = []
        self._oversize_streak = 0
        self._oversize_notice_emitted = False
        self._resync_ground_streak = 0
        self._resync_air_streak = 0

    def _process_frame(self, frame: LedFrame) -> List[FootEvent]:
        cluster = self._extract_primary_cluster(frame.bits, min_length=1)
        self._last_primary_cluster = cluster
        ratio = cluster.ratio if cluster else 0.0
        centroid = cluster.centroid_cm if cluster else None
        dt = max(frame.timestamp - (self._prev_time or frame.timestamp), 1e-3)
        self._prev_time = frame.timestamp
        self._prev_ratio = ratio
        events: List[FootEvent] = []

        cluster_length = cluster.length if cluster else 0
        oversized = cluster_length > self.touch_max_cluster_length
        if oversized:
            self._oversize_streak += 1
            if (
                self._oversize_streak >= self.confirm_samples
                and not self._oversize_notice_emitted
            ):
                self._quality_notices.append(
                    DetectorQualityNotice(
                        kind="contact_cluster_above_limit",
                        time=frame.timestamp,
                        cluster_length=cluster_length,
                        ratio=ratio,
                    )
                )
                self._oversize_notice_emitted = True
        else:
            self._oversize_streak = 0
            self._oversize_notice_emitted = False

        if self._state == "resync":
            ground_condition = (
                self.touch_min_cluster_length
                <= cluster_length
                <= self.touch_max_cluster_length
            )
            air_condition = cluster_length < self.touch_min_cluster_length
            if ground_condition:
                self._resync_ground_streak += 1
                self._resync_air_streak = 0
                if self._resync_ground_streak >= self.confirm_samples:
                    self._state = "ground"
                    self._resync_ground_streak = 0
            elif air_condition:
                self._resync_air_streak += 1
                self._resync_ground_streak = 0
                if self._resync_air_streak >= self.confirm_samples:
                    self._state = "air"
                    self._resync_air_streak = 0
            else:
                self._resync_ground_streak = 0
                self._resync_air_streak = 0
            return events

        touch_condition = (
            self._state == "air"
            and self.touch_min_cluster_length
            <= cluster_length
            <= self.touch_max_cluster_length
        )
        lift_condition = (
            self._state == "ground"
            and cluster_length < self.touch_min_cluster_length
        )

        if touch_condition:
            self._touch_streak += 1
            self._lift_streak = max(0, self._lift_streak - 1)
            if self._touch_streak >= self.confirm_samples:
                events.append(FootEvent("touch", frame.timestamp, ratio, centroid))
                self._state = "ground"
                self._touch_streak = 0
        elif lift_condition:
            self._lift_streak += 1
            self._touch_streak = max(0, self._touch_streak - 1)
            if self._lift_streak >= self.confirm_samples:
                events.append(FootEvent("lift", frame.timestamp, ratio, centroid))
                self._state = "air"
                self._lift_streak = 0
        else:
            self._touch_streak = max(0, self._touch_streak - 1)
            self._lift_streak = max(0, self._lift_streak - 1)
        return events

    def _extract_primary_cluster(
        self, bits: Sequence[int], min_length: int = 10
    ) -> Optional[Cluster]:
        active = [idx for idx, val in enumerate(bits) if val]
        if not active:
            return None
        clusters = list(self._split_clusters(active))
        if not clusters:
            return None
        primary_cluster = max(clusters, key=lambda cl: cl.length)
        if primary_cluster.length < min_length:
            return None
        return primary_cluster

    def _split_clusters(self, active_indices: Sequence[int]) -> Iterable[Cluster]:
        if not active_indices:
            return []
        start = active_indices[0]
        prev = start
        for idx in active_indices[1:]:
            if idx - prev > self.gap_threshold:
                yield self._make_cluster(start, prev)
                start = idx
            prev = idx
        yield self._make_cluster(start, prev)

    def _make_cluster(self, start: int, end: int) -> Cluster:
        length = end - start + 1
        centroid_idx = (start + end) / 2.0
        centroid_cm = centroid_idx * self.spacing_cm
        ratio = length / self.cols
        return Cluster(start, end, length, centroid_idx, centroid_cm, ratio)


# ===================== NPZ 文件读取与帧提取 =====================

class NpzFrameReader:
    """从 .npz 文件读取原始字节流并解析为 LED 帧序列"""

    def __init__(self, npz_path: str, frame_size: int = 12):
        """
        参数：
          - npz_path: .npz 文件路径
          - frame_size: 每帧字节数（默认 12 字节 = 96 位）
        """
        self.npz_path = npz_path
        self.frame_size = frame_size
        self.raw: Optional[np.ndarray] = None
        self.meta: Optional[dict] = None

    def load(self) -> None:
        """加载 .npz 文件"""
        if not os.path.exists(self.npz_path):
            raise FileNotFoundError(f"文件不存在: {self.npz_path}")

        data = np.load(self.npz_path, allow_pickle=True)
        self.raw = data["raw"]

        # 解析元数据
        meta_raw = data["meta"]
        if hasattr(meta_raw, "item"):
            meta_raw = meta_raw.item()
        self.meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw

    def get_meta(self) -> dict:
        """返回元数据"""
        if self.meta is None:
            self.load()
        return self.meta or {}

    def iter_frames_simple(self) -> Generator[LedFrame, None, None]:
        """
        简单模式：按固定字节数切割原始数据，不经过协议解析。
        适用于已知数据格式为"连续 12 字节帧"的情况。
        """
        if self.raw is None:
            self.load()

        raw_bytes = bytes(self.raw)
        total_frames = len(raw_bytes) // self.frame_size
        meta = self.get_meta()
        duration = meta.get("duration_s", 1.0)
        # 估算帧间隔（假设均匀分布）
        dt = duration / max(total_frames, 1)

        for i in range(total_frames):
            start = i * self.frame_size
            end = start + self.frame_size
            frame_bytes = raw_bytes[start:end]
            bits = self._bytes_to_bits(frame_bytes)

            # 跳过全 0 或全 1 帧（异常帧）
            ones = sum(bits)
            if ones == 0 or ones == len(bits):
                continue

            timestamp = i * dt
            yield LedFrame(timestamp, bits)

    def iter_frames_protocol(self) -> Generator[LedFrame, None, None]:
        """
        协议模式：使用 protocol_parser 解析原始字节流中的帧。
        适用于数据中包含完整协议帧（帧头、类型、载荷、CRC、帧尾）的情况。
        """
        if self.raw is None:
            self.load()

        if protocol_parser is None:
            print("警告: protocol 模块不可用，回退到简单模式")
            yield from self.iter_frames_simple()
            return

        buf = bytearray(bytes(self.raw))
        meta = self.get_meta()
        start_ts = meta.get("start_ts", 0.0)
        frame_count = 0

        while len(buf) > 0:
            ret, frame_type, ack, subpack, status = protocol_parser(buf)
            if ret != 0:
                # 解析失败，丢弃一个字节继续
                if len(buf) > 0:
                    buf.pop(0)
                continue

            if frame_type != E_DATA_REPORT or subpack is None:
                continue

            # 提取载荷
            payload = getattr(subpack, "buffer", b"") or b""
            if len(payload) < 12:
                continue

            bits = self._bytes_to_bits(payload[:12])
            ones = sum(bits)
            if ones == 0 or ones == len(bits):
                continue

            # 使用相对帧计数估算时间戳（基于录制时长和总帧数）
            # 帧索引可能是设备侧的绝对计数，这里改用相对计数
            frame_count += 1

            yield LedFrame(float(frame_count), bits)  # 先用帧计数，后续按总帧数归一化

    @staticmethod
    def _bytes_to_bits(payload: bytes) -> List[int]:
        """将 12 字节转换为 96 位列表"""
        bits: List[int] = []
        for b in payload[:12]:
            for i in range(8):
                bits.append((b >> i) & 0x1)
        # 语义归一化：1 = 遮挡/触地，0 = 未遮挡
        bits = [1 - x for x in bits[:96]]
        return bits


# ===================== 主函数 =====================

def run_analysis(args: argparse.Namespace) -> int:
    """运行离线步态分析"""

    # 加载数据
    print(f"加载文件: {args.file}")
    reader = NpzFrameReader(args.file, frame_size=args.frame_size)
    try:
        reader.load()
    except Exception as e:
        print(f"加载失败: {e}")
        return 1

    # 打印元数据
    meta = reader.get_meta()
    print(f"元数据:")
    print(f"  录制时长: {meta.get('duration_s', 'N/A')}s")
    raw_len = len(reader.raw) if reader.raw is not None else 0
    print(f"  总字节数: {meta.get('bytes_total', raw_len)}")
    print(f"  设备: VID={meta.get('vid', 'N/A')} PID={meta.get('pid', 'N/A')}")
    print()

    # 选择帧迭代模式
    if args.protocol:
        print("使用协议解析模式...")
        frames = list(reader.iter_frames_protocol())
    else:
        print("使用简单切割模式...")
        frames = list(reader.iter_frames_simple())

    print(f"解析得到 {len(frames)} 帧有效数据")
    if not frames:
        print("没有有效帧，退出")
        return 0

    # 将帧时间戳归一化为实际秒数（基于录制时长）
    duration = meta.get("duration_s", 1.0)
    if len(frames) > 1:
        # 协议模式下 timestamp 是帧计数，需要归一化
        max_ts = max(f.timestamp for f in frames)
        min_ts = min(f.timestamp for f in frames)
        ts_range = max_ts - min_ts if max_ts > min_ts else 1.0
        for f in frames:
            f.timestamp = (f.timestamp - min_ts) / ts_range * duration

    # 计算并显示采样率
    sample_rate = len(frames) / duration if duration > 0 else 0
    print(f"估算采样率: {sample_rate:.1f} Hz")
    print()

    # 初始化检测器
    detector = SingleFootDetector(
        touch_ratio_threshold=args.touch_threshold,
        lift_ratio_threshold=args.lift_threshold,
        confirm_samples=args.confirm_samples,
    )

    # 处理所有帧
    all_events: List[FootEvent] = []
    last_ev: Optional[FootEvent] = None
    start_ts = frames[0].timestamp if frames else 0.0

    for frame in frames:
        for ev in detector.consume(frame):
            # 若已有上一条事件，安全输出它
            if last_ev is not None:
                all_events.append(last_ev)
            last_ev = ev

    # 循环结束后：如果最后一条是触地则保留，腾空则丢弃
    if last_ev is not None and last_ev.kind.lower() == "touch":
        all_events.append(last_ev)

    # 输出结果
    print()
    print(f"检测到 {len(all_events)} 个步态事件:")
    print("-" * 60)
    for ev in all_events:
        stage = "触地阶段" if ev.kind.lower() == "touch" else "腾空阶段"
        time_str = f"{ev.time:.3f}s"
        ratio_str = f"{ev.ratio:.3f}"
        centroid_str = f"{ev.centroid_cm:.2f}cm" if ev.centroid_cm is not None else "N/A"
        print(f"{stage} 时刻={time_str} 遮挡率={ratio_str} 质心位置={centroid_str}")

    # 统计摘要
    touches = [e for e in all_events if e.kind.lower() == "touch"]
    lifts = [e for e in all_events if e.kind.lower() == "lift"]
    print("-" * 60)
    print(f"统计: 触地 {len(touches)} 次, 腾空 {len(lifts)} 次")

    # 计算步态周期（触地到触地的间隔）
    if len(touches) >= 2:
        intervals = [touches[i + 1].time - touches[i].time for i in range(len(touches) - 1)]
        avg_interval = sum(intervals) / len(intervals)
        print(f"平均步态周期: {avg_interval:.3f}s ({60 / avg_interval:.1f} 步/分钟)")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="离线步态数据解析器 - 从 .npz 文件分析步态事件"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        required=True,
        help="输入的 .npz 文件路径（由 data_source.py 录制）"
    )
    parser.add_argument(
        "--protocol",
        action="store_true",
        help="使用协议解析模式（数据含完整帧结构）；默认使用简单切割模式"
    )
    parser.add_argument(
        "--frame-size",
        type=int,
        default=12,
        help="每帧字节数（简单模式下使用，默认 12）"
    )
    parser.add_argument(
        "--touch-threshold",
        type=float,
        default=0.12,
        help="触地判定阈值（遮挡率，默认 0.12）"
    )
    parser.add_argument(
        "--lift-threshold",
        type=float,
        default=0.05,
        help="腾空判定阈值（遮挡率，默认 0.05）"
    )
    parser.add_argument(
        "--confirm-samples",
        type=int,
        default=2,
        help="确认所需连续帧数（默认 2）"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_analysis(args)


if __name__ == "__main__":
    sys.exit(main())
