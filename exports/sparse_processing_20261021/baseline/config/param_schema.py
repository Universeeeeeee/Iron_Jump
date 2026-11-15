"""
param_schema.py — 参数 Schema 加载器

从 Iron_parameters.json 加载完整的参数定义，提供按 test_type 过滤、
枚举值约束查询、visibility_condition 动态可见性判定等能力。

设计原则:
  - 只读解析，不修改 JSON
  - 所有查询方法均为纯函数，无副作用
  - 对外提供 ParamDef 数据类，屏蔽 JSON 内部结构差异
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ParamDef:
    """单个参数的定义 — 从 JSON 解析后的统一视图"""
    name: str
    display_name: str
    description: str
    param_type: str                   # "enum" | "integer" | "float" | "string" | "boolean"
    priority: str = "core"            # "core" | "optional"
    layer: int = 0                    # 所属层级 (1-4)
    category: str = ""                # 所属分组名称

    # 枚举值 (已按 test_type 过滤后的纯字符串列表)
    values: list[str] = field(default_factory=list)

    # 数值约束
    default: Any = None
    unit: str = ""
    range_str: str = ""               # 原始 range 字符串, 如 "1-99"
    step: float | None = None
    format_str: str = ""              # 格式, 如 "mm:ss"

    # 联动字段
    enables_fields: list[str] = field(default_factory=list)
    visibility_condition: dict | None = None  # e.g. {"stop_type": "Status change"}

    # 备注
    note: str = ""
    source: str = ""


class ParamSchema:
    """
    参数 Schema — 从 Iron_parameters.json 加载并提供查询接口。

    用法::

        schema = ParamSchema()
        params = schema.get_params_for_test("Jump Test")
        visible = schema.get_visible_params("Jump Test", {"stop_type": "End of Time"})
        values = schema.get_enum_values("stop_type", "Jump Test")
    """

    def __init__(self, json_path: str | Path | None = None):
        if json_path is None:
            json_path = Path(__file__).parent / "Iron_parameters.json"
        self._json_path = Path(json_path)
        self._raw: list[dict] = []
        self._all_params: list[ParamDef] = []
        self._load()

    # ------------------------------------------------------------------
    #  公共查询接口
    # ------------------------------------------------------------------

    def get_params_for_test(self, test_type: str) -> list[ParamDef]:
        """获取指定测试类型的所有可用参数 (不考虑 visibility_condition)。"""
        return [p for p in self._all_params if self._param_applies(p, test_type)]

    def visible_params_for_test(self, test_type: str) -> list[ParamDef]:
        """
        获取指定测试类型的所有可见参数 (不考虑 visibility_condition 动态联动)。

        相当于 get_params_for_test 的别名，供需要过滤 applicable_tests 但
        不需要 visibility_condition 联动判定的场景使用。
        """
        return self.get_params_for_test(test_type)

    def get_visible_params(
        self, test_type: str, current_values: dict[str, Any]
    ) -> list[ParamDef]:
        """
        获取当前参数组合下实际可见的参数列表。

        在 get_params_for_test 的基础上，进一步按 visibility_condition 过滤。
        例如 stop_type="End of Time" 时，finish_position 和 number_of_jumps 不可见，
        但 test_length 可见。
        """
        result = []
        for p in self.get_params_for_test(test_type):
            if self._is_visible(p, test_type, current_values):
                result.append(p)
        return result

    def get_enum_values(self, param_name: str, test_type: str) -> list[str]:
        """获取指定参数在指定测试类型下的可用枚举值。

        对于结构化枚举（values 中每个值有自己的 applicable_tests），
        会按 test_type 过滤，只返回该测试类型可用的值。
        """
        raw_param = self._find_raw_param(param_name)
        if raw_param is None:
            return []
        return self._extract_enum_values(raw_param, test_type)

    def get_param_def(self, param_name: str) -> ParamDef | None:
        """按名称查找参数定义。"""
        for p in self._all_params:
            if p.name == param_name:
                return p
        return None

    def validate(self, test_type: str, values: dict[str, Any]) -> list[str]:
        """
        校验参数值的合法性，返回错误消息列表。空列表表示全部通过。

        校验规则:
          1. core 参数不能缺失
          2. enum 值必须在允许范围内
          3. 数值参数必须在 range 范围内
          4. visibility_condition 不满足的字段不做校验
        """
        errors = []
        visible = self.get_visible_params(test_type, values)
        visible_names = {p.name for p in visible}

        for p in visible:
            val = values.get(p.name)

            # 1. core 参数不能缺失
            if p.priority == "core" and val is None:
                errors.append(f"缺少必填参数: {p.display_name}")
                continue

            if val is None:
                continue

            # 2. 枚举值校验
            if p.param_type == "enum" and p.values:
                if val not in p.values:
                    errors.append(
                        f"{p.display_name}: '{val}' 不在允许范围 {p.values} 内"
                    )

            # 3. 数值范围校验
            if p.param_type in ("integer", "float") and p.range_str:
                self._validate_range(p, val, errors)

        return errors

    # ------------------------------------------------------------------
    #  内部加载逻辑
    # ------------------------------------------------------------------

    def _load(self):
        """加载并解析 JSON 文件。"""
        with open(self._json_path, "r", encoding="utf-8") as f:
            self._raw = json.load(f)

        for layer_obj in self._raw:
            layer_num = layer_obj.get("layer", 0)
            category = layer_obj.get("category", "")

            # Layer 1 和 Layer 4: 直接 parameters 列表
            if "parameters" in layer_obj:
                for raw_p in layer_obj["parameters"]:
                    self._all_params.append(
                        self._parse_param(raw_p, layer_num, category)
                    )

            # Layer 2 和 Layer 3: sub_categories 嵌套
            if "sub_categories" in layer_obj:
                for sub_cat in layer_obj["sub_categories"]:
                    sub_name = sub_cat.get("name", "")
                    for raw_p in sub_cat.get("parameters", []):
                        self._all_params.append(
                            self._parse_param(raw_p, layer_num, sub_name)
                        )

    def _parse_param(self, raw: dict, layer: int, category: str) -> ParamDef:
        """将单个 JSON 参数对象解析为 ParamDef。"""
        # 处理 range: 可能是字符串或 per-test-type dict
        range_val = raw.get("range", "")
        if isinstance(range_val, dict):
            # 取第一个值作为展示用，实际校验时按 test_type 查
            range_str = str(range_val)
        else:
            range_str = str(range_val) if range_val else ""

        # 处理 values: 可能是纯字符串列表或结构化对象列表
        raw_values = raw.get("values", [])
        if raw_values and isinstance(raw_values[0], str):
            values = list(raw_values)
        else:
            # 结构化值 — 存储所有 value 字符串，per-test 过滤在查询时做
            values = [v["value"] for v in raw_values if isinstance(v, dict)]

        # 处理 visibility_condition
        vis_cond = raw.get("visibility_condition")

        return ParamDef(
            name=raw["name"],
            display_name=raw.get("display_name", raw["name"]),
            description=raw.get("description", ""),
            param_type=raw.get("type", "string"),
            priority=raw.get("priority", "core"),
            layer=layer,
            category=category,
            values=values,
            default=raw.get("default"),
            unit=raw.get("unit", ""),
            range_str=range_str,
            step=raw.get("step"),
            format_str=raw.get("format", ""),
            enables_fields=raw.get("enables_fields", []),
            visibility_condition=vis_cond,
            note=raw.get("note", ""),
            source=raw.get("source", ""),
        )

    # ------------------------------------------------------------------
    #  内部查询辅助
    # ------------------------------------------------------------------

    def _param_applies(self, p: ParamDef, test_type: str) -> bool:
        """判断参数是否适用于指定测试类型。"""
        raw = self._find_raw_param(p.name)
        if raw is None:
            return True  # 无 applicable_tests 约束 → 适用于所有类型

        applicable = raw.get("applicable_tests")
        if applicable is None:
            return True
        return test_type in applicable

    def _is_visible(
        self, p: ParamDef, test_type: str, current_values: dict[str, Any]
    ) -> bool:
        """根据 visibility_condition 判定参数是否可见。"""
        if p.visibility_condition is None:
            return True

        vc = p.visibility_condition

        # 格式 1: 简单 dict, e.g. {"stop_type": "Status change"}
        # 含义: 当 stop_type 的值为 "Status change" 时可见
        if isinstance(vc, dict):
            # 检查是否是 per-test-type 格式
            # e.g. {"Jump Test": {"stop_type": "Status change"}, "Sprint...": {...}}
            if test_type in vc:
                condition = vc[test_type]
                return self._eval_condition(condition, current_values)
            elif any(isinstance(v, dict) for v in vc.values()):
                # vc 的值中有 dict → 这是 per-test-type 格式，但当前 test_type 不在其中
                # 说明此字段对当前 test_type 不可见
                return False
            else:
                # 简单 dict 格式, 适用于所有 test_type
                return self._eval_condition(vc, current_values)

        return True

    @staticmethod
    def _eval_condition(condition: dict, current_values: dict) -> bool:
        """评估单个条件 dict, e.g. {"stop_type": "Status change"}。"""
        for field_name, expected_value in condition.items():
            actual = current_values.get(field_name)
            if actual != expected_value:
                return False
        return True

    def _find_raw_param(self, name: str) -> dict | None:
        """从原始 JSON 中按名称查找参数定义。"""
        for layer_obj in self._raw:
            if "parameters" in layer_obj:
                for p in layer_obj["parameters"]:
                    if p.get("name") == name:
                        return p
            if "sub_categories" in layer_obj:
                for sub_cat in layer_obj["sub_categories"]:
                    for p in sub_cat.get("parameters", []):
                        if p.get("name") == name:
                            return p
        return None

    def _extract_enum_values(self, raw_param: dict, test_type: str) -> list[str]:
        """从原始 JSON 参数中提取适用于指定 test_type 的枚举值。"""
        raw_values = raw_param.get("values", [])
        if not raw_values:
            return []

        # 纯字符串列表
        if isinstance(raw_values[0], str):
            return list(raw_values)

        # 结构化对象列表 — 按 applicable_tests 过滤
        result = []
        for v in raw_values:
            if not isinstance(v, dict):
                continue
            applicable = v.get("applicable_tests")
            if applicable is None or test_type in applicable:
                result.append(v["value"])
        return result

    def _validate_range(self, p: ParamDef, val: Any, errors: list[str]):
        """校验数值参数的范围。"""
        if p.default is not None and val == p.default:
            return
        range_str = p.range_str
        if not range_str or range_str.startswith("{"):
            return  # dict 格式的 range 暂不做自动校验

        try:
            parts = range_str.split("-")
            if len(parts) == 2:
                lo, hi = float(parts[0]), float(parts[1])
                num_val = float(val)
                if num_val < lo or num_val > hi:
                    errors.append(
                        f"{p.display_name}: {val} 超出范围 [{lo}, {hi}]"
                    )
        except (ValueError, TypeError):
            pass  # 无法解析的 range 格式，跳过校验


# 模块级便捷实例
_default_schema: ParamSchema | None = None


def get_schema() -> ParamSchema:
    """获取默认 ParamSchema 实例（单例，延迟加载）。"""
    global _default_schema
    if _default_schema is None:
        _default_schema = ParamSchema()
    return _default_schema
