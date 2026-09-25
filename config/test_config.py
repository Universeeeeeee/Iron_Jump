"""
test_config.py — 测试运行时配置容器

一次测试的完整参数集，由 UI 的 ParamPanel 构建，
传入 GaitEngine 驱动算法行为。

当前版本仅包含 Jump Test 相关字段。
其他测试类型的字段将在后续迭代中扩展。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Union

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig


@dataclass
class TestConfig:
    """
    一次测试的完整运行时配置。

    由 UI ParamPanel.get_config() 构建，传入 GaitEngine。
    GaitEngine 根据此配置初始化检测器参数和停止条件。

    用法::

        config = TestConfig(
            test_type="Jump Test",
            stop_type="Status change",
            number_of_jumps=5,
            min_contact_time=60,
        )
        engine = GaitEngine(config=config)
    """

    # ---- Layer 1: 测试类型 ----
    test_type: str = "Jump Test"

    # ---- Layer 2: 主配置参数 ----
    start_type: str = "Status change"
    start_position: str = "Inside area"
    stop_type: str = "Status change"

    # 条件字段 (可见性取决于 stop_type)
    finish_position: Optional[str] = None     # stop_type=Status change 时有效
    number_of_jumps: Optional[int] = None     # stop_type=Status change 时有效
    test_length: Optional[str] = None         # stop_type=End of Time 时有效, 格式 "mm:ss"

    # 可选主参数
    starting_foot: str = "Not defined"

    # ---- Layer 3: 滤波参数 ----
    min_contact_time: int = 60                # ms, 低于此值的接触视为无效
    min_flight_time: int = 0                  # ms, 低于此值的腾空视为无效, 0=禁用
    max_flight_time: int = 0                  # ms, 超过此值的腾空直接丢弃, 0=禁用
    flight_time_review_threshold: int = 700  # ms, 超过时仅标记复核，不自动丢弃

    # ---- Layer 4: 可选反馈参数 ----
    metronome_enabled: bool = False
    metronome_bpm: int = 120

    # ------------------------------------------------------------------
    #  序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，跳过 None 值。"""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestConfig:
        """从字典构建 TestConfig，忽略未知字段。"""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    # ------------------------------------------------------------------
    #  便捷方法
    # ------------------------------------------------------------------

    def get_test_length_seconds(self) -> Optional[int]:
        """将 test_length "mm:ss" 格式转换为总秒数。"""
        if not self.test_length:
            return None
        try:
            parts = self.test_length.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            pass
        return None

    @property
    def has_auto_stop(self) -> bool:
        """当前配置是否支持自动停止。"""
        if self.stop_type == "Status change" and self.number_of_jumps:
            return True
        if self.stop_type == "End of Time" and self.test_length:
            return True
        return False

    @property
    def mode_label(self) -> str:
        """获取模式的中文显示标签。"""
        labels = {
            "Jump Test": "纵跳",
            "Sprint and Gait Test": "步态分析",
            "Treadmill Running Test": "跑步机跑步",
            "Treadmill Gait Test": "跑步机步态",
            "Tapping Test": "Tapping",
            "Reaction Times": "反应时",
            "Static Test (Sway)": "静态测试",
        }
        return labels.get(self.test_type, self.test_type)


# ---- 多态配置类型别名 ----

AnyTestConfig = Union[TestConfig, WalkingConfig, OvergroundRunningConfig, TreadmillGaitConfig, TreadmillRunningConfig]


def config_from_dict(data: dict[str, Any]) -> AnyTestConfig:
    """根据 test_type 分发构造对应配置对象。所有字段名与 JSON/UI 一致，无需映射。"""
    test_type = data.get("test_type", "Jump Test")
    payload = {key: value for key, value in data.items() if key != "test_type"}

    if test_type == "Overground Running Test":
        known = {n for n, f in OvergroundRunningConfig.__dataclass_fields__.items() if f.init}
        return OvergroundRunningConfig(**{k: v for k, v in payload.items() if k in known and v is not None})
    if test_type == "Sprint and Gait Test":
        known = {name for name, f in WalkingConfig.__dataclass_fields__.items() if f.init}
        return WalkingConfig(**{k: v for k, v in payload.items() if k in known and v is not None})
    if test_type == "Treadmill Gait Test":
        known = {f.name for f in TreadmillGaitConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in payload.items() if k in known}
        filtered.setdefault("test_length", None)
        return TreadmillGaitConfig(**filtered)
    if test_type == "Treadmill Running Test":
        known = {f.name for f in TreadmillRunningConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in payload.items() if k in known}
        filtered.setdefault("test_length", None)
        return TreadmillRunningConfig(**filtered)
    return TestConfig.from_dict(data)


# ---- 预设配置工厂 ----

def default_jump_config() -> TestConfig:
    """创建 Jump Test 的默认配置。"""
    return TestConfig(
        test_type="Jump Test",
        start_type="Status change",
        start_position="Inside area",
        stop_type="Status change",
        finish_position="Inside area",
        number_of_jumps=5,
        starting_foot="Not defined",
        min_contact_time=60,
        min_flight_time=0,
        max_flight_time=0,
        flight_time_review_threshold=700,
        metronome_enabled=False,
        metronome_bpm=120,
    )
