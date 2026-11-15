"""
test_report.py — 不可变测试结果快照

由 SessionController 在测试结束时从 GaitEngine 提取数据构造。
ReportView 只依赖此 dataclass，不依赖 GaitEngine。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional, Union

from config.treadmill_report import TreadmillGaitReport, TreadmillRunningReport

G = 9.81  # 重力加速度


def _positive_values(values) -> tuple[float, ...]:
    return tuple(float(value) for value in values if value > 0)


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0


def _min_or_zero(values: tuple[float, ...]) -> float:
    return min(values) if values else 0.0


def _max_or_zero(values: tuple[float, ...]) -> float:
    return max(values) if values else 0.0


def _population_std(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _jump_heights(air_times: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(0.5 * G * (air_time / 2) ** 2 for air_time in air_times)


def _cadences(cycle_times: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(60.0 / cycle_time for cycle_time in cycle_times)


@dataclass(frozen=True)
class JumpResultRecord:
    """一次已闭合腾空的时序与质量快照。"""

    index: int
    lift_time_s: float | None
    touch_time_s: float | None
    air_time_s: float | None
    jump_height_m: float | None
    contact_time_s: float | None
    cycle_time_s: float | None
    cadence_jumps_per_min: float | None
    is_included_in_statistics: bool
    statistics_exclusion_reason: str | None = None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class JumpQualityNoticeRecord:
    """不构成正式触地事件的检测质量提示。"""

    kind: str
    time_s: float
    cluster_length: int
    ratio: float


@dataclass(frozen=True)
class JumpTestReport:
    """纵跳测试结果快照（不可变）"""
    touch_count: int
    lift_count: int
    air_times: tuple[float, ...]
    contact_times: tuple[float, ...]
    cycle_times: tuple[float, ...]
    # 派生指标
    avg_jump_height: float
    max_jump_height: float
    avg_air_time: float
    max_air_time: float
    avg_contact_time: float
    avg_cadence: Optional[float]   # 60/avg_cycle, 无数据时 None
    finish_reason: str             # "jump_count_reached" | "time_up" | "manual"
    jump_heights: tuple[float, ...] = ()
    cadences: tuple[float, ...] = ()
    min_jump_height: float = 0.0
    std_jump_height: float = 0.0
    min_air_time: float = 0.0
    std_air_time: float = 0.0
    min_contact_time: float = 0.0
    max_contact_time: float = 0.0
    std_contact_time: float = 0.0
    # 原始导出帧 (可选，用于 Excel 导出)
    export_frames: tuple = ()
    export_timestamps: tuple = ()
    jump_results: tuple[JumpResultRecord, ...] = ()
    quality_notices: tuple[JumpQualityNoticeRecord, ...] = ()
    report_config_snapshot: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GaitTestReport:
    """步态测试结果快照（不可变）"""
    touch_count: int
    lift_count: int
    stride_lengths: tuple
    velocities: tuple
    avg_stride: Optional[float]
    max_stride: Optional[float]
    avg_velocity: Optional[float]
    max_velocity: Optional[float]
    # 支撑时间
    foot_a_support_times: tuple = ()
    foot_b_support_times: tuple = ()
    # 高阶指标
    imbalance_index: Optional[float] = None
    avg_double_support: Optional[float] = None
    avg_single_support: Optional[float] = None
    avg_acceleration: Optional[float] = None
    finish_reason: str = "manual"
    # 原始导出帧
    export_frames: tuple = ()
    export_timestamps: tuple = ()
    visual_timeline: tuple = ()
    walking_summary: dict = field(default_factory=dict)
    report_config_snapshot: dict = field(default_factory=dict)


# 统一类型别名
from config.overground_running_report import OvergroundRunningReport

TestReport = Union[
    OvergroundRunningReport,
    JumpTestReport,
    GaitTestReport,
    TreadmillGaitReport,
    TreadmillRunningReport,
]


def build_report(engine, reason: str = "manual") -> TestReport:
    """从 GaitEngine 实例提取数据，构造不可变报告。

    Thin wrapper delegating to engine.build_report(reason).

    必须在线程停止后、engine 引用释放前调用。
    """
    return engine.build_report(reason)
