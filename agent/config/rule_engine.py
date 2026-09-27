# rule_engine.py — Config Agent 规则引擎（离线模式）
# 根据用户信息自动推荐 OptoJump 测试参数，无需网络连接
#
# 数据流:
#   test_type (str) + AthleteProfile → TestConfig
#   输出与 ParamPanel.get_config() 完全一致，可直接传入 GaitEngine

from __future__ import annotations

from dataclasses import fields, replace
from typing import Callable

from config.config_validation import validate_runtime_config
from config.test_config import AnyTestConfig, TestConfig, default_jump_config
from config.treadmill_config import (
    default_treadmill_gait_config,
    default_treadmill_running_config,
)
from .models import AthleteProfile
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig


# ---- 参数修正规则 ----
#
# 格式: (条件函数, 要覆盖的 TestConfig 字段字典)
#
# 规则按列表顺序逐条应用，后面的规则覆盖前面的。
#
# 扩展方式:
#   1. 添加新规则 — 在列表末尾追加 (条件函数, 覆盖字典) 元组
#   2. 可覆盖的字段 — TestConfig 的任意字段:
#      stop_type, number_of_jumps, test_length,
#      min_contact_time, min_flight_time, max_flight_time, ...
#   3. 条件函数签名: (AthleteProfile) -> bool
#
ProfileRule = tuple[Callable[[AthleteProfile], bool], dict]

PROFILE_RULES: list[ProfileRule] = [
    # 年长用户 (>60): 触地时间更长，减少跳跃次数
    (lambda ctx: ctx.age > 60,
     {"min_contact_time": 80, "number_of_jumps": 3}),

    # 儿童 (<12): 触地时间更短
    (lambda ctx: ctx.age < 12,
     {"min_contact_time": 40, "number_of_jumps": 3}),

    # 入门用户: 保守参数
    (lambda ctx: ctx.level == "beginner",
     {"min_contact_time": 100, "number_of_jumps": 3}),
]


class RuleEngine:
    """
    规则引擎 — 根据用户信息自动调整测试参数

    职责:
      - 按测试模式选择独立默认工厂
      - 按用户条件逐条修正配置字段
      - 用统一运行时校验器校验输出合法性

    不做:
      - 不识别意图（test_type 由 UI 直接传入）
      - 不涉及 LLM（纯规则映射）
    """

    def configure(self, test_type: str, ctx: AthleteProfile) -> AnyTestConfig:
        """
        生成测试配置。

        Args:
            test_type: 测试类型字符串，如 "Jump Test"
            ctx: 用户运动档案

        Returns:
            AnyTestConfig — 与 ParamPanel.get_config() 输出格式一致

        Raises:
            ValueError: 如果生成的配置未通过 schema 校验
        """
        factories = {
            "Jump Test": default_jump_config,
            "Treadmill Gait Test": default_treadmill_gait_config,
            "Treadmill Running Test": default_treadmill_running_config,
            "Sprint and Gait Test": WalkingConfig,
            "Overground Running Test": OvergroundRunningConfig,
        }
        try:
            config = factories[test_type]()
        except KeyError as exc:
            raise ValueError(f"不支持的离线测试类型: {test_type}") from exc

        # 2. 按用户条件修正
        if not isinstance(config, (WalkingConfig, OvergroundRunningConfig)):
            config = self._apply_rules(config, ctx)

        # 3. schema 校验
        self._validate(config)

        return config

    # 保守聚合：多条规则命中同一字段时取最保守值，不依赖规则顺序
    _MERGE_MAX = {"min_contact_time", "min_flight_time"}       # 越大越保守
    _MERGE_MIN = {"number_of_jumps"}                           # 越小越保守
    _MERGE_MIN_NONZERO = {"max_flight_time"}                   # 0=禁用，非零值越小越保守

    def _apply_rules(
        self, config: AnyTestConfig, ctx: AthleteProfile
    ) -> AnyTestConfig:
        """收集匹配规则的覆盖值，保守聚合后应用到 config。"""
        collected: dict[str, list] = {}
        for condition_fn, overrides in PROFILE_RULES:
            if condition_fn(ctx):
                for field_name, value in overrides.items():
                    collected.setdefault(field_name, []).append(value)

        # 聚合
        merged = {}
        for field_name, values in collected.items():
            if field_name in self._MERGE_MAX:
                merged[field_name] = max(values)
            elif field_name in self._MERGE_MIN:
                merged[field_name] = min(values)
            elif field_name in self._MERGE_MIN_NONZERO:
                nonzero = [v for v in values if v != 0]
                merged[field_name] = min(nonzero) if nonzero else 0
            else:
                # 未明确定义聚合策略的字段：取最后一个匹配规则的值（兼容扩展）
                merged[field_name] = values[-1]

        available_fields = {item.name for item in fields(config)}
        applicable = {
            field_name: value
            for field_name, value in merged.items()
            if field_name in available_fields
        }
        if isinstance(config, TestConfig):
            for field_name, value in applicable.items():
                setattr(config, field_name, value)
            return config
        return replace(config, **applicable)

    def normalize_runtime_config(
        self, config: AnyTestConfig, ctx: AthleteProfile
    ) -> AnyTestConfig:
        """Replace model-selected technical filters with profile policy values."""
        policy = self.configure(config.test_type, ctx)
        intent_fields = {
            "Jump Test": {
                "test_type", "start_type", "start_position", "stop_type",
                "finish_position", "number_of_jumps", "test_length",
                "starting_foot",
            },
            "Treadmill Gait Test": {
                "stop_type", "test_length", "treadmill_speed", "direction",
            },
            "Treadmill Running Test": {
                "stop_type", "test_length", "treadmill_speed", "direction",
            },
            "Sprint and Gait Test": {"stop_type", "starting_foot"},
            "Overground Running Test": {"stop_type", "starting_foot"},
        }[config.test_type]
        technical_values = {
            item.name: getattr(policy, item.name)
            for item in fields(policy)
            if item.init and item.name not in intent_fields
        }
        if isinstance(config, TestConfig):
            normalized = TestConfig.from_dict(config.to_dict())
            for field_name, value in technical_values.items():
                setattr(normalized, field_name, value)
            return normalized
        return replace(config, **technical_values)

    def _validate(self, config: AnyTestConfig) -> None:
        """Use the common runtime validator for every supported mode."""
        errors = validate_runtime_config(config)
        if errors:
            raise ValueError(f"规则引擎生成的配置不合法: {errors}")
