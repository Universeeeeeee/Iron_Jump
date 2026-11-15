"""
行走步态分析器 - 从 .npz 文件解析光电阵列数据并计算步态参数

Usage::

    python spatial_clusterer.py --file walking_data.npz --protocol

本脚本基于 npz 文件解析光电阵列遮挡信号，分析正常行走（walking gait）的步态参数。

核心功能：
  - 簇（cluster）提取与跨帧追踪
  - 行走方向自动推断
  - 左右脚（FootA/FootB）标记
  - 步态参数计算：步幅、步速、支撑时间、步态周期等

数据来源：data_source.py 录制的 .npz 文件
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Generator, List, Optional, Sequence, Tuple

import numpy as np

# 复用协议解析器
try:
    from .protocol import E_DATA_REPORT, protocol_parser
except Exception:
    try:
        from hardware.protocol import E_DATA_REPORT, protocol_parser
    except Exception:
        E_DATA_REPORT = 0x82
        protocol_parser = None  # type: ignore


# ===================== 常量与默认参数 =====================

COLS = 96                      # LED 总数
SPACING_CM = 1.04              # 相邻 LED 间距（厘米）
MIN_CLUSTER_LENGTH = 10        # 最小簇宽度（LED 数）
T_MIN_MS = 50                  # 最小触底时间（毫秒），用于伪簇剔除
MAX_SHIFT_LED = 6              # 跨帧簇关联的最大质心偏移（LED 数）
GAP_THRESHOLD = 1              # 簇内允许的最大 LED 间隙


# ===================== 数据结构 =====================

@dataclass
class LedFrame:
    """单帧 LED 状态"""
    timestamp: float           # 时间戳（秒）
    bits: Sequence[int]        # 96 位状态，1=遮挡，0=未遮挡


@dataclass
class Cluster:
    """单帧内的簇（连续遮挡段）"""
    start: int                 # 起始 LED 索引
    end: int                   # 结束 LED 索引
    length: int                # 遮挡宽度（LED 数）
    centroid_idx: float        # 质心索引
    centroid_cm: float         # 质心物理位置（厘米）


@dataclass
class TrackedCluster:
    """跨帧追踪的簇（脚）"""
    track_id: int              # 追踪 ID
    appear_time: float         # 首次出现时间（秒）
    disappear_time: float      # 最后出现时间（秒）
    centroid_start: float      # 首次出现时的质心位置（cm）
    centroid_end: float        # 最后出现时的质心位置（cm）
    foot_label: Optional[str] = None  # "A" 或 "B"，用于左右脚区分
    length_cm: float = 0.0     # 最新簇宽度 (cm)
    cluster_start_cm: float | None = None
    cluster_end_cm: float | None = None
    seen_count: int = 0        # 累计被观测帧数
    miss_count: int = 0        # 连续丢失帧数
    is_active: bool = True     # 是否仍活跃
    # 生命周期内的质心轨迹
    centroid_history: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class GaitEvent:
    """步态事件"""
    event_type: str            # "foot_strike" 或 "toe_off"
    time: float                # 事件时间（秒）
    foot_label: Optional[str]  # "A" 或 "B"
    centroid_cm: float         # 事件发生时的质心位置


@dataclass
class GaitCycle:
    """单个步态周期的参数"""
    foot_label: str            # 该周期对应的脚
    strike_time: float         # 触地时间
    toe_off_time: float        # 离地时间
    support_duration: float    # 支撑时间（秒）
    stride_length_cm: Optional[float] = None  # 步幅（厘米）
    stride_time: Optional[float] = None       # 步态周期（秒）
    step_time: Optional[float] = None         # 步时（秒）
    velocity_cm_s: Optional[float] = None     # 步速（厘米/秒）


# ===================== 簇提取（单帧） =====================

def extract_clusters(
    bits: Sequence[int],
    min_length: int = MIN_CLUSTER_LENGTH,
    gap_threshold: int = GAP_THRESHOLD,
    spacing_cm: float = SPACING_CM,
) -> List[Cluster]:
    """
    从单帧 LED 状态中提取所有有效簇。

    参数:
        bits: 96 位 LED 状态，1=遮挡
        min_length: 最小簇宽度（LED 数）
        gap_threshold: 簇内允许的最大间隙
        spacing_cm: LED 间距

    返回:
        有效簇列表
    """
    # 找出所有遮挡的 LED 索引
    active = [idx for idx, val in enumerate(bits) if val]
    if not active:
        return []

    # 按间隙分割成多个簇
    clusters: List[Cluster] = []
    start = active[0]
    prev = start

    for idx in active[1:]:
        if idx - prev > gap_threshold:
            # 间隙超过阈值，结束当前簇
            cluster = _make_cluster(start, prev, spacing_cm)
            if cluster.length >= min_length:
                clusters.append(cluster)
            start = idx
        prev = idx

    # 处理最后一个簇
    cluster = _make_cluster(start, prev, spacing_cm)
    if cluster.length >= min_length:
        clusters.append(cluster)

    return clusters


def _make_cluster(start: int, end: int, spacing_cm: float) -> Cluster:
    """创建簇对象"""
    length = end - start + 1
    centroid_idx = (start + end) / 2.0
    centroid_cm = centroid_idx * spacing_cm
    return Cluster(start, end, length, centroid_idx, centroid_cm)


# ===================== 跨帧簇追踪 =====================

class ClusterTracker:
    """
    跨帧簇追踪器。
    
    使用质心最近匹配策略，追踪簇的生命周期。
    """

    def __init__(
        self,
        max_shift_led: int = MAX_SHIFT_LED,
        t_min_s: float = T_MIN_MS / 1000.0,
        spacing_cm: float = SPACING_CM,
        max_missed_frames: int = 5,
    ):
        self.max_shift_led = max_shift_led
        self.max_shift_cm = max_shift_led * spacing_cm
        self.t_min_s = t_min_s
        self.spacing_cm = spacing_cm
        self.max_missed_frames = max_missed_frames

        self._next_track_id = 0
        self._active_tracks: Dict[int, TrackedCluster] = {}  # track_id -> TrackedCluster
        self._completed_tracks: List[TrackedCluster] = []

    def update(self, timestamp: float, clusters: List[Cluster]) -> None:
        """
        用当前帧的簇更新追踪状态。

        参数:
            timestamp: 当前帧时间戳
            clusters: 当前帧提取的簇列表
        """
        # 贪心匹配：为每个当前簇找最近的活跃追踪
        used_tracks = set()
        matched_clusters = set()
        matches: List[Tuple[int, int, float]] = []  # (track_id, cluster_idx, distance)

        for track_id, track in self._active_tracks.items():
            for ci, cluster in enumerate(clusters):
                dist = abs(track.centroid_end - cluster.centroid_cm)
                if dist <= self.max_shift_cm:
                    matches.append((track_id, ci, dist))

        # 按距离排序，贪心匹配
        matches.sort(key=lambda x: x[2])
        for track_id, ci, dist in matches:
            if track_id in used_tracks or ci in matched_clusters:
                continue
            # 匹配成功，更新追踪
            track = self._active_tracks[track_id]
            cluster = clusters[ci]
            track.disappear_time = timestamp
            track.centroid_end = cluster.centroid_cm
            track.length_cm = cluster.length * self.spacing_cm
            track.cluster_start_cm = cluster.start * self.spacing_cm
            track.cluster_end_cm = cluster.end * self.spacing_cm
            track.centroid_history.append((timestamp, cluster.centroid_cm))
            track.seen_count += 1
            track.miss_count = 0
            used_tracks.add(track_id)
            matched_clusters.add(ci)

        # 未匹配的活跃追踪容忍度检查
        to_remove = []
        for track_id, track in self._active_tracks.items():
            if track_id not in used_tracks:
                track.miss_count += 1
                if track.miss_count > self.max_missed_frames:
                    track.is_active = False
                    to_remove.append(track_id)

        for track_id in to_remove:
            self._completed_tracks.append(self._active_tracks.pop(track_id))

        # 未匹配的簇开始新追踪
        for ci, cluster in enumerate(clusters):
            if ci not in matched_clusters:
                new_track = TrackedCluster(
                    track_id=self._next_track_id,
                    appear_time=timestamp,
                    disappear_time=timestamp,
                    centroid_start=cluster.centroid_cm,
                    centroid_end=cluster.centroid_cm,
                    length_cm=cluster.length * self.spacing_cm,
                    cluster_start_cm=cluster.start * self.spacing_cm,
                    cluster_end_cm=cluster.end * self.spacing_cm,
                    seen_count=1,
                    miss_count=0,
                    is_active=True,
                    centroid_history=[(timestamp, cluster.centroid_cm)],
                )
                self._active_tracks[self._next_track_id] = new_track
                self._next_track_id += 1

    def get_active_tracks_view(self) -> List[dict]:
        """为上层提供统一结构视图"""
        return [
            {
                "track_id": track.track_id,
                "centroid_cm": track.centroid_end,
                "length_cm": track.length_cm,
                "cluster_start_cm": track.cluster_start_cm,
                "cluster_end_cm": track.cluster_end_cm,
                "seen_count": track.seen_count,
                "miss_count": track.miss_count,
            }
            for track in self._active_tracks.values()
        ]

    def finalize(self) -> List[TrackedCluster]:
        """
        结束追踪，返回所有有效簇（已剔除伪簇）。

        返回:
            有效簇列表，按 appear_time 排序
        """
        # 将仍活跃的追踪加入完成列表
        for track in self._active_tracks.values():
            self._completed_tracks.append(track)
        self._active_tracks.clear()

        # 伪簇剔除：持续时间 < t_min_s 的簇无效
        valid_tracks = [
            t for t in self._completed_tracks
            if (t.disappear_time - t.appear_time) >= self.t_min_s
        ]

        # 按出现时间排序
        valid_tracks.sort(key=lambda t: t.appear_time)
        return valid_tracks


# ===================== 行走方向推断 =====================

def infer_walking_direction(tracks: List[TrackedCluster]) -> str:
    """
    基于有效簇质心变化趋势推断行走方向。

    参数:
        tracks: 有效簇列表

    返回:
        "positive"（LED 索引增大方向）、"negative"（减小方向）或 "unknown"
    """
    if len(tracks) < 2:
        return "unknown"

    # 计算每个簇的 Δc = centroid_end - centroid_start
    delta_c_list = []
    for track in tracks:
        delta_c = track.centroid_end - track.centroid_start
        # 只统计有明显位移的簇（排除原地不动的情况）
        if abs(delta_c) > 1.0:  # 阈值 1cm
            delta_c_list.append(delta_c)

    if len(delta_c_list) < 2:
        return "unknown"

    # 统计方向
    positive_count = sum(1 for dc in delta_c_list if dc > 0)
    negative_count = sum(1 for dc in delta_c_list if dc < 0)
    total = positive_count + negative_count

    if total == 0:
        return "unknown"

    # 需要超过 60% 的一致性
    if positive_count / total >= 0.6:
        return "positive"
    elif negative_count / total >= 0.6:
        return "negative"
    else:
        return "unknown"


# ===================== FootA/FootB 标记 =====================

def assign_foot_labels(
    tracks: List[TrackedCluster],
    direction: str,
) -> List[TrackedCluster]:
    """
    为有效簇分配 FootA/FootB 标签。

    规则：
        - 第一个出现的有效簇记为 FootA
        - 与其时间上交替出现、且在空间位置上位于其前方（沿行走方向）的簇记为 FootB
        - 后续簇按时间交替关系继承标签

    参数:
        tracks: 有效簇列表（已按 appear_time 排序）
        direction: 行走方向

    返回:
        标记后的簇列表
    """
    if not tracks:
        return tracks

    if direction == "unknown":
        # 方向未知时，仅按时间交替分配
        for i, track in enumerate(tracks):
            track.foot_label = "A" if i % 2 == 0 else "B"
        return tracks

    # 第一个簇为 FootA
    tracks[0].foot_label = "A"
    last_foot = "A"
    last_centroid = tracks[0].centroid_start

    for track in tracks[1:]:
        # 判断当前簇相对于上一个簇的位置
        if direction == "positive":
            # 正方向：质心更大的是"前方"
            is_ahead = track.centroid_start > last_centroid
        else:
            # 负方向：质心更小的是"前方"
            is_ahead = track.centroid_start < last_centroid

        # 交替逻辑：如果在前方且与上一个脚不同，则切换
        if is_ahead:
            track.foot_label = "B" if last_foot == "A" else "A"
        else:
            # 在后方，保持交替
            track.foot_label = "B" if last_foot == "A" else "A"

        last_foot = track.foot_label
        last_centroid = track.centroid_start

    return tracks


# ===================== 步态事件与参数计算 =====================

def extract_gait_events(tracks: List[TrackedCluster]) -> List[GaitEvent]:
    """
    从追踪簇中提取步态事件（触地、离地）。

    返回:
        事件列表，按时间排序
    """
    events: List[GaitEvent] = []

    for track in tracks:
        # 触地事件
        events.append(GaitEvent(
            event_type="foot_strike",
            time=track.appear_time,
            foot_label=track.foot_label,
            centroid_cm=track.centroid_start,
        ))
        # 离地事件
        events.append(GaitEvent(
            event_type="toe_off",
            time=track.disappear_time,
            foot_label=track.foot_label,
            centroid_cm=track.centroid_end,
        ))

    # 按时间排序
    events.sort(key=lambda e: e.time)
    return events


def compute_gait_parameters(
    tracks: List[TrackedCluster],
    events: List[GaitEvent],
) -> Tuple[List[GaitCycle], Dict[str, float]]:
    """
    计算步态参数。

    返回:
        (各步态周期列表, 统计摘要字典)
    """
    cycles: List[GaitCycle] = []

    # 按脚分组
    foot_a_tracks = [t for t in tracks if t.foot_label == "A"]
    foot_b_tracks = [t for t in tracks if t.foot_label == "B"]

    def compute_for_foot(foot_tracks: List[TrackedCluster], foot_label: str):
        for i, track in enumerate(foot_tracks):
            cycle = GaitCycle(
                foot_label=foot_label,
                strike_time=track.appear_time,
                toe_off_time=track.disappear_time,
                support_duration=track.disappear_time - track.appear_time,
            )

            # 步态周期：同侧相邻触地间隔
            if i + 1 < len(foot_tracks):
                next_track = foot_tracks[i + 1]
                cycle.stride_time = next_track.appear_time - track.appear_time
                # 步幅：同侧相邻触地的质心位移
                cycle.stride_length_cm = abs(next_track.centroid_start - track.centroid_start)
                # 步速
                if cycle.stride_time > 0:
                    cycle.velocity_cm_s = cycle.stride_length_cm / cycle.stride_time

            cycles.append(cycle)

    compute_for_foot(foot_a_tracks, "A")
    compute_for_foot(foot_b_tracks, "B")

    # 计算 step time（相邻两次触地，不区分脚）
    all_strikes = sorted(
        [(t.appear_time, t.centroid_start) for t in tracks],
        key=lambda x: x[0]
    )
    step_times = []
    step_lengths = []
    for i in range(len(all_strikes) - 1):
        step_time = all_strikes[i + 1][0] - all_strikes[i][0]
        step_length = abs(all_strikes[i + 1][1] - all_strikes[i][1])
        step_times.append(step_time)
        step_lengths.append(step_length)

    # 为 cycles 填充 step_time（取相邻触地间隔）
    cycles_sorted = sorted(cycles, key=lambda c: c.strike_time)
    for i, cycle in enumerate(cycles_sorted):
        if i < len(step_times):
            cycle.step_time = step_times[i]

    # 统计摘要
    summary: Dict[str, float] = {}

    support_durations = [c.support_duration for c in cycles]
    if support_durations:
        summary["avg_support_time_s"] = sum(support_durations) / len(support_durations)

    stride_times = [c.stride_time for c in cycles if c.stride_time is not None]
    if stride_times:
        summary["avg_stride_time_s"] = sum(stride_times) / len(stride_times)
        summary["cadence_steps_per_min"] = 60.0 / summary["avg_stride_time_s"] * 2  # 双步

    stride_lengths = [c.stride_length_cm for c in cycles if c.stride_length_cm is not None]
    if stride_lengths:
        summary["avg_stride_length_cm"] = sum(stride_lengths) / len(stride_lengths)

    velocities = [c.velocity_cm_s for c in cycles if c.velocity_cm_s is not None]
    if velocities:
        summary["avg_velocity_cm_s"] = sum(velocities) / len(velocities)
        summary["avg_velocity_m_s"] = summary["avg_velocity_cm_s"] / 100.0

    if step_times:
        summary["avg_step_time_s"] = sum(step_times) / len(step_times)

    if step_lengths:
        summary["avg_step_length_cm"] = sum(step_lengths) / len(step_lengths)

    # 单脚支撑/双脚支撑时间（简化估算）
    # 单脚支撑 ≈ 步时 - 双脚支撑时间
    # 这里暂用支撑时间作为近似
    summary["foot_a_count"] = len(foot_a_tracks)
    summary["foot_b_count"] = len(foot_b_tracks)

    return cycles, summary


# ===================== NPZ 文件读取（复用） =====================

class NpzFrameReader:
    """从 .npz 文件读取原始字节流并解析为 LED 帧序列"""

    def __init__(self, npz_path: str, frame_size: int = 12):
        self.npz_path = npz_path
        self.frame_size = frame_size
        self.raw: Optional[np.ndarray] = None
        self.meta: Optional[dict] = None

    def load(self) -> None:
        if not os.path.exists(self.npz_path):
            raise FileNotFoundError(f"文件不存在: {self.npz_path}")

        data = np.load(self.npz_path, allow_pickle=True)
        self.raw = data["raw"]

        meta_raw = data["meta"]
        if hasattr(meta_raw, "item"):
            meta_raw = meta_raw.item()
        self.meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw

    def get_meta(self) -> dict:
        if self.meta is None:
            self.load()
        return self.meta or {}

    def iter_frames_protocol(self) -> Generator[LedFrame, None, None]:
        """协议模式解析"""
        if self.raw is None:
            self.load()

        if protocol_parser is None:
            print("警告: protocol 模块不可用")
            return

        buf = bytearray(bytes(self.raw))
        frame_count = 0

        while len(buf) > 0:
            ret, frame_type, ack, subpack, status = protocol_parser(buf)
            if ret != 0:
                if len(buf) > 0:
                    buf.pop(0)
                continue

            if frame_type != E_DATA_REPORT or subpack is None:
                continue

            payload = getattr(subpack, "buffer", b"") or b""
            if len(payload) < 12:
                continue

            bits = self._bytes_to_bits(payload[:12])
            ones = sum(bits)
            if ones == 0 or ones == len(bits):
                continue

            frame_count += 1
            yield LedFrame(float(frame_count), bits)

    @staticmethod
    def _bytes_to_bits(payload: bytes) -> List[int]:
        bits: List[int] = []
        for b in payload[:12]:
            for i in range(8):
                bits.append((b >> i) & 0x1)
        bits = [1 - x for x in bits[:96]]
        return bits


# ===================== 主分析函数 =====================

def analyze_walking_gait(
    frames: List[LedFrame],
    duration_s: float,
    min_cluster_length: int = MIN_CLUSTER_LENGTH,
    t_min_ms: float = T_MIN_MS,
    max_shift_led: int = MAX_SHIFT_LED,
    spacing_cm: float = SPACING_CM,
) -> Tuple[List[TrackedCluster], List[GaitEvent], List[GaitCycle], Dict[str, float], str]:
    """
    行走步态分析主函数。

    参数:
        frames: LED 帧列表
        duration_s: 总录制时长
        其他: 可配置参数

    返回:
        (有效簇列表, 事件列表, 步态周期列表, 统计摘要, 行走方向)
    """
    # 1. 归一化时间戳
    if len(frames) > 1:
        max_ts = max(f.timestamp for f in frames)
        min_ts = min(f.timestamp for f in frames)
        ts_range = max_ts - min_ts if max_ts > min_ts else 1.0
        for f in frames:
            f.timestamp = (f.timestamp - min_ts) / ts_range * duration_s

    # 2. 初始化追踪器
    tracker = ClusterTracker(
        max_shift_led=max_shift_led,
        t_min_s=t_min_ms / 1000.0,
        spacing_cm=spacing_cm,
    )

    # 3. 逐帧处理
    for frame in frames:
        clusters = extract_clusters(
            frame.bits,
            min_length=min_cluster_length,
            spacing_cm=spacing_cm,
        )
        tracker.update(frame.timestamp, clusters)

    # 4. 获取有效簇
    valid_tracks = tracker.finalize()

    if not valid_tracks:
        return [], [], [], {}, "unknown"

    # 5. 推断行走方向
    direction = infer_walking_direction(valid_tracks)

    # 6. 分配 FootA/FootB 标签
    valid_tracks = assign_foot_labels(valid_tracks, direction)

    # 7. 提取步态事件
    events = extract_gait_events(valid_tracks)

    # 8. 计算步态参数
    cycles, summary = compute_gait_parameters(valid_tracks, events)

    summary["direction"] = 1 if direction == "positive" else (-1 if direction == "negative" else 0)
    summary["total_tracks"] = len(valid_tracks)
    summary["sample_rate_hz"] = len(frames) / duration_s if duration_s > 0 else 0

    return valid_tracks, events, cycles, summary, direction


# ===================== 命令行接口 =====================

def run_analysis(args: argparse.Namespace) -> int:
    """运行行走步态分析"""

    print(f"加载文件: {args.file}")
    reader = NpzFrameReader(args.file)
    try:
        reader.load()
    except Exception as e:
        print(f"加载失败: {e}")
        return 1

    meta = reader.get_meta()
    duration_s = meta.get("duration_s", 1.0)

    print(f"元数据:")
    print(f"  录制时长: {duration_s:.3f}s")
    raw_len = len(reader.raw) if reader.raw is not None else 0
    print(f"  总字节数: {meta.get('bytes_total', raw_len)}")
    print(f"  设备: VID={meta.get('vid', 'N/A')} PID={meta.get('pid', 'N/A')}")
    print()

    print("使用协议解析模式...")
    frames = list(reader.iter_frames_protocol())
    print(f"解析得到 {len(frames)} 帧有效数据")

    if not frames:
        print("没有有效帧，退出")
        return 0

    # 执行分析
    tracks, events, cycles, summary, direction = analyze_walking_gait(
        frames,
        duration_s,
        min_cluster_length=args.min_cluster_length,
        t_min_ms=args.t_min_ms,
        max_shift_led=args.max_shift_led,
        spacing_cm=args.spacing_cm,
    )

    # 输出结果
    print()
    print("=" * 60)
    print("行走步态分析结果")
    print("=" * 60)

    direction_str = {
        "positive": "正向（LED索引增大）",
        "negative": "负向（LED索引减小）",
        "unknown": "未知",
    }.get(direction, direction)
    print(f"推断行走方向: {direction_str}")
    print(f"有效簇数量: {len(tracks)}")
    print(f"估算采样率: {summary.get('sample_rate_hz', 0):.1f} Hz")
    print()

    # 步态事件
    print("-" * 60)
    print("步态事件序列:")
    print("-" * 60)
    for ev in events:
        event_str = "触地" if ev.event_type == "foot_strike" else "离地"
        foot_str = f"Foot{ev.foot_label}" if ev.foot_label else "?"
        print(f"  {event_str} {foot_str} @ {ev.time:.3f}s  质心={ev.centroid_cm:.2f}cm")

    # 各步详情
    print()
    print("-" * 60)
    print("各步态周期详情:")
    print("-" * 60)
    for i, cycle in enumerate(sorted(cycles, key=lambda c: c.strike_time)):
        print(f"  [{i+1}] Foot{cycle.foot_label}:")
        print(f"      触地时间: {cycle.strike_time:.3f}s")
        print(f"      离地时间: {cycle.toe_off_time:.3f}s")
        print(f"      支撑时间: {cycle.support_duration:.3f}s")
        if cycle.stride_length_cm is not None:
            print(f"      步幅: {cycle.stride_length_cm:.2f}cm")
        if cycle.stride_time is not None:
            print(f"      步态周期: {cycle.stride_time:.3f}s")
        if cycle.velocity_cm_s is not None:
            print(f"      步速: {cycle.velocity_cm_s:.2f}cm/s ({cycle.velocity_cm_s/100:.2f}m/s)")

    # 统计摘要
    print()
    print("-" * 60)
    print("统计摘要:")
    print("-" * 60)
    if "avg_support_time_s" in summary:
        print(f"  平均支撑时间: {summary['avg_support_time_s']:.3f}s")
    if "avg_stride_time_s" in summary:
        print(f"  平均步态周期: {summary['avg_stride_time_s']:.3f}s")
    if "avg_step_time_s" in summary:
        print(f"  平均步时: {summary['avg_step_time_s']:.3f}s")
    if "avg_stride_length_cm" in summary:
        print(f"  平均步幅: {summary['avg_stride_length_cm']:.2f}cm")
    if "avg_step_length_cm" in summary:
        print(f"  平均步长: {summary['avg_step_length_cm']:.2f}cm")
    if "avg_velocity_m_s" in summary:
        print(f"  平均步速: {summary['avg_velocity_m_s']:.2f}m/s")
    if "cadence_steps_per_min" in summary:
        print(f"  步频: {summary['cadence_steps_per_min']:.1f} 步/分钟")
    print(f"  FootA 步数: {summary.get('foot_a_count', 0)}")
    print(f"  FootB 步数: {summary.get('foot_b_count', 0)}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="行走步态分析器 - 从 .npz 文件分析行走步态参数"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        required=True,
        help="输入的 .npz 文件路径"
    )
    parser.add_argument(
        "--min-cluster-length",
        type=int,
        default=MIN_CLUSTER_LENGTH,
        help=f"最小簇宽度（LED 数，默认 {MIN_CLUSTER_LENGTH}）"
    )
    parser.add_argument(
        "--t-min-ms",
        type=float,
        default=T_MIN_MS,
        help=f"最小触底时间（毫秒，默认 {T_MIN_MS}）"
    )
    parser.add_argument(
        "--max-shift-led",
        type=int,
        default=MAX_SHIFT_LED,
        help=f"跨帧簇关联最大偏移（LED 数，默认 {MAX_SHIFT_LED}）"
    )
    parser.add_argument(
        "--spacing-cm",
        type=float,
        default=SPACING_CM,
        help=f"LED 间距（厘米，默认 {SPACING_CM}）"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_analysis(args)


if __name__ == "__main__":
    sys.exit(main())
