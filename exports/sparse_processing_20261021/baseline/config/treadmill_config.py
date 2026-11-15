"""
treadmill_config.py — 跑步机测试配置数据模型

定义了 TreadmillGaitConfig 和 TreadmillRunningConfig 两个不可变 dataclass，
以及辅助校验函数和类型别名。

当前阶段的字段名与 Iron_parameters.json / UI schema 保持一致，不进行字段名映射。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


# ---- 类型别名 ----

TreadmillTestType = Literal["Treadmill Gait Test", "Treadmill Running Test"]
TreadmillStopType = Literal["Software command", "End of Time"]
Direction = Literal["Interface side", "Opposite side"]
StepLengthCalculation = Literal["Tip-to-Tip", "Heel-to-Heel"]
FootSide = Literal["left", "right", "unknown"]        # 脚的标识
FootSideOverride = Literal["left", "right"]          # starting_foot_override 不允许 unknown
FootLengthSource = Literal["captured", "manual", "unknown"]
StartingFootSource = Literal[
    "auto_first_contact",
    "auto_double_support_front",
    "manual_override",
    "manual_correction",
    "unknown",
]


# ---- 校验辅助函数 ----

def _is_mmss(value: str) -> bool:
    """校验 mm:ss 格式 + 说明书范围 00:01-59:59。"""
    import re as _re
    m = _re.match(r"^(\d{1,2}):(\d{2})$", value)
    if not m:
        return False
    minutes, seconds = int(m.group(1)), int(m.group(2))
    return 0 <= minutes <= 59 and 0 <= seconds <= 59 and (minutes > 0 or seconds > 0)


def get_test_length_seconds(value: str | None) -> int | None:
    """将 mm:ss 格式转为总秒数，供算法层使用。"""
    if not value:
        return None
    minute_text, second_text = value.split(":", 1)
    return int(minute_text) * 60 + int(second_text)


# ---- 基础配置 ----

@dataclass(frozen=True)
class TreadmillBaseConfig:
    """跑步机通用配置字段。"""
    stop_type: TreadmillStopType
    test_length: str | None
    treadmill_speed: float = 3.0
    direction: Direction = "Opposite side"
    min_contact_time: int = 60
    min_flight_time: int = 0
    max_flight_time: int = 0
    step_length_calculation: StepLengthCalculation = "Tip-to-Tip"
    min_foot_length: float = 10.0
    filter_gaitr_in: int = 0
    filter_gaitr_out: int = 0
    foot_length_cm_snapshot: float | None = None
    foot_length_source: FootLengthSource = "unknown"
    starting_foot_override: FootSideOverride | None = None

    def __post_init__(self) -> None:
        if not 0.1 <= self.treadmill_speed <= 20.0:
            raise ValueError("treadmill_speed must be between 0.1 and 20.0")
        if self.test_length is not None and not _is_mmss(self.test_length):
            raise ValueError("test_length must be a valid mm:ss string")
        if self.stop_type == "End of Time" and self.test_length is None:
            raise ValueError("test_length is required when stop_type is End of Time")
        if self.min_contact_time < 0 or self.min_flight_time < 0 or self.max_flight_time < 0:
            raise ValueError("time filters must be non-negative")
        if self.min_foot_length <= 0:
            raise ValueError("min_foot_length must be positive")
        if any(not isinstance(value, int) or not 0 <= value < 96
               for value in (self.filter_gaitr_in, self.filter_gaitr_out)):
            raise ValueError("GaitR filters must be integer LED thresholds from 0 to 95")

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    def get_test_length_seconds(self) -> int | None:
        """将 test_length 'mm:ss' 格式转换为总秒数。"""
        if not self.test_length:
            return None
        minute_text, second_text = self.test_length.split(":", 1)
        return int(minute_text) * 60 + int(second_text)


@dataclass(frozen=True)
class TreadmillGaitConfig(TreadmillBaseConfig):
    """跑步机步态测试配置。"""
    min_step_length: float = 10.0
    automatic_data_filter: int = 0

    @property
    def test_type(self) -> str:
        return "Treadmill Gait Test"

    @property
    def mode_label(self) -> str:
        return "跑步机步态"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.min_step_length <= 0:
            raise ValueError("min_step_length must be positive")
        if self.automatic_data_filter not in (0, *range(10, 91)):
            raise ValueError("automatic_data_filter must be 0 or 10-90")

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["test_type"] = self.test_type
        return data


@dataclass(frozen=True)
class TreadmillRunningConfig(TreadmillBaseConfig):
    """跑步机跑步测试配置。"""
    min_gap_between_feet: float = 10.0

    @property
    def test_type(self) -> str:
        return "Treadmill Running Test"

    @property
    def mode_label(self) -> str:
        return "跑步机跑步"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.min_gap_between_feet <= 0:
            raise ValueError("min_gap_between_feet must be positive")

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["test_type"] = self.test_type
        return data


def default_treadmill_gait_config() -> TreadmillGaitConfig:
    """Create the schema-aligned default treadmill gait configuration."""
    return TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.0,
        direction="Opposite side",
    )


def default_treadmill_running_config() -> TreadmillRunningConfig:
    """Create the schema-aligned default treadmill running configuration."""
    return TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=6.0,
        direction="Opposite side",
    )
