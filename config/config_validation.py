"""Single final validation entry point for every configuration source."""

from __future__ import annotations

from config.param_schema import get_schema
from config.test_config import AnyTestConfig


SUPPORTED_TEST_TYPES = {
    "Jump Test",
    "Sprint and Gait Test",
    "Overground Running Test",
    "Treadmill Gait Test",
    "Treadmill Running Test",
}


def validate_runtime_config(config: AnyTestConfig) -> list[str]:
    """Return user-facing errors for a runtime configuration."""
    test_type = config.test_type
    if test_type not in SUPPORTED_TEST_TYPES:
        return [f"测试类型尚未接入正式流程: {test_type}"]

    if test_type in {"Sprint and Gait Test", "Overground Running Test"}:
        import math
        errors = []
        if config.stop_type not in {"Status change", "Software command"}:
            errors.append("地面测试结束方式请选择自动结束或手动结束。")
        if config.starting_foot not in {"Left", "Right", "Not defined"}:
            errors.append("起始脚请选择左脚、右脚或未指定。")
        from config.walking_config import WalkingConfig
        from config.overground_running_config import OvergroundRunningConfig
        defaults = OvergroundRunningConfig() if test_type == "Overground Running Test" else WalkingConfig()
        names = ["min_contact_time", "confirmation_ms", "release_ms", "exit_clear_ms", "stop_threshold_s"]
        if test_type == "Overground Running Test":
            names.append("toe_platform_ms")
        for name in names:
            value = getattr(config, name, getattr(defaults, name))
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                errors.append(f"{name} 必须是有限正数。")
        return errors

    values = config.to_dict()
    values.setdefault(
        "test_macro_type",
        "Performance" if test_type == "Jump Test" else "Gait Analysis",
    )
    if test_type.startswith("Treadmill "):
        values.setdefault("start_type", "Software command")

    errors = get_schema().validate(test_type, values)

    stop_type = getattr(config, "stop_type", None)
    if stop_type == "Status change" and not getattr(config, "number_of_jumps", None):
        errors.append("按状态结束时必须设置目标跳跃次数。")
    if stop_type == "End of Time":
        try:
            seconds = config.get_test_length_seconds()
        except (TypeError, ValueError):
            seconds = None
        if not seconds or seconds <= 0:
            errors.append("按时间结束时必须设置有效测试时长。")

    if getattr(config, "start_type", None) == "External impulse":
        errors.append("External impulse 已从当前硬件和配置流程移除。")
    if getattr(config, "metronome_enabled", False):
        errors.append("节拍器尚未接入当前运行流程。")

    return list(dict.fromkeys(errors))
