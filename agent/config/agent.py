# agent.py — Config Agent（在线模式）
# 使用 Pydantic AI + DeepSeek LLM 进行智能参数配置
#
# 数据流:
#   用户自然语言 + AthleteProfile
#     → Pydantic AI (Union[LLMTestConfig, ChatResponse])
#     → LLM 自主选择: 自然语言回复 或 结构化配置
#     → 配置路径: LLMTestConfig → TestConfig → ParamSchema 校验
#     → 返回 (TestConfig | None, 回复文字)

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Union, Callable

import httpx
from pydantic_ai import Agent

from config.config_validation import validate_runtime_config
from config.test_config import TestConfig, AnyTestConfig
from agent.common.model_provider import build_chat_model, build_http_client, default_model_settings
from .models import AthleteProfile, LLMTestConfig, ChatResponse, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig
from .rule_engine import RuleEngine
from .modes import MODE_TEST_TYPES


# ---- Load System Prompts ----
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(name: str) -> str:
    """从 agent/prompts/ 加载 prompt 文件内容。"""
    path = _PROMPT_DIR / name
    return path.read_text(encoding="utf-8").strip()


# ---- System Prompt (instance property, loaded per mode in __init__) ----


def _format_runtime_context(ctx: AthleteProfile, mode: str = "jump") -> str:
    """将本地上下文注入 prompt，避免为已知数据额外发起 tool 往返。"""
    if ctx.history:
        recent = ctx.history[-3:]
        history_text = "\n".join(
            f"- {h.get('date', '')}: {h.get('test_type', '')}, "
            f"jumps={h.get('number_of_jumps', '')}, "
            f"min_contact={h.get('min_contact_time', '')}ms"
            for h in recent
        )
    else:
        history_text = "该用户无历史测试记录"

    level_labels = {"beginner": "入门", "intermediate": "进阶", "advanced": "高阶"}

    return (
        "用户信息：\n"
        f"- 年龄: {ctx.age}\n"
        f"- 体重: {ctx.weight}kg\n"
        f"- 身高: {ctx.height}cm\n"
        f"- 训练水平: {level_labels.get(ctx.level, ctx.level)}\n"
        f"- 侧重训练: {ctx.focus_side or '均衡'}\n"
        "历史记录：\n"
        f"{history_text}\n"
        "设备能力：\n"
        f"- 设备通道数: {ctx.device_channels or '尚未识别'}\n"
        "- 采样率: 1000Hz (硬件固定)\n"
        f"- 当前支持的测试类型: {MODE_TEST_TYPES[mode]}"
    )


class LLMConfigAgent:
    """
    LLM 配置 Agent — 支持多轮对话，管理对话历史。

    延迟初始化: Agent 实例在首次调用 chat() 时才创建，
    避免仅导入此模块就触发 .env 加载和网络连接。
    """

    # ---- ClarifyGPT 配置 ----
    N_SAMPLES = 3         # 总采样次数（含首次）
    MIN_CONFIG_COUNT = 3  # 三次采样都必须生成配置，才进入一致性比较
    FIELD_LABELS = {
        "stop_type": "停止方式",
        "number_of_jumps": "跳跃次数",
        "test_length": "测试时长",
        "treadmill_speed": "跑步机速度",
        "direction": "跑步方向",
        "starting_foot": "起始脚",
    }
    STRONG_CONFIG_PHRASES = (
        "配置",
        "配参数",
        "帮我配",
        "生成参数",
        "设置参数",
        "设参数",
    )
    CONFIG_ACTION_TERMS = (
        "测试",
        "测",
        "纵跳",
        "跳跃",
        "跳",
        "开始",
        "停止",
        "jump",
        "test",
    )
    CONFIG_CONSTRAINT_TERMS = (
        "次",
        "分钟",
        "秒",
        "时长",
        "手动",
        "自动",
        "起跳",
        "双脚",
        "单脚",
        "次数",
        "参数",
        "minute",
        "second",
        "times",
    )
    CURRENT_CONFIG_QUERY_TERMS = (
        "展示",
        "显示",
        "输出",
        "查看",
        "列出",
        "表格",
        "完整",
        "当前",
        "详情",
        "show",
        "display",
        "table",
        "list",
    )
    CONFIG_REFERENCE_TERMS = ("配置", "参数", "config", "setting")

    PROMPT_MAP = {
        "jump": "jump.md",
        "treadmill_gait": "treadmill_gait.md",
        "treadmill_running": "treadmill_running.md",
        "walking": "walking.md",
        "overground_running": "overground_running.md",
    }

    MODE_CONSENSUS_FIELDS = {
        "jump": [
            "start_type", "start_position", "stop_type", "finish_position",
            "number_of_jumps", "test_length", "starting_foot",
        ],
        "treadmill_gait": ["treadmill_speed", "direction", "stop_type", "test_length"],
        "treadmill_running": ["treadmill_speed", "direction", "stop_type", "test_length"],
        "walking": ["stop_type", "starting_foot"],
        "overground_running": ["stop_type", "starting_foot"],
    }

    MODE_OUTPUT_TYPES = {
        "jump": Union[LLMTestConfig, ChatResponse],
        "treadmill_gait": Union[LLMTreadmillGaitConfig, ChatResponse],
        "treadmill_running": Union[LLMTreadmillRunningConfig, ChatResponse],
        "walking": Union[LLMWalkingConfig, ChatResponse],
        "overground_running": Union[LLMOvergroundRunningConfig, ChatResponse],
    }

    def __init__(self, mode: str = "jump"):
        if mode not in MODE_TEST_TYPES:
            raise ValueError(f"不支持的智能配置模式: {mode}")
        self._mode = mode
        self.message_history = None
        self._last_config: AnyTestConfig | None = None
        self._CONSENSUS_FIELDS = self.MODE_CONSENSUS_FIELDS.get(
            mode, self.MODE_CONSENSUS_FIELDS["jump"]
        )
        self._system_prompt = _load_prompt(self.PROMPT_MAP.get(mode, self.PROMPT_MAP["jump"]))

    @staticmethod
    def _make_agent(http_client: httpx.AsyncClient, mode: str = "jump") -> Agent:
        """用 fresh http_client 创建 Agent，绕过 pydantic-ai 全局缓存。

        mode 决定 output_type Union:
          - "jump" → Union[LLMTestConfig, ChatResponse]
          - "treadmill_gait" → Union[LLMTreadmillGaitConfig, ChatResponse]
          - "treadmill_running" → Union[LLMTreadmillRunningConfig, ChatResponse]
        """
        if mode not in MODE_TEST_TYPES:
            raise ValueError(f"不支持的智能配置模式: {mode}")
        model = build_chat_model(http_client)
        output_type = LLMConfigAgent.MODE_OUTPUT_TYPES.get(
            mode, LLMConfigAgent.MODE_OUTPUT_TYPES["jump"]
        )
        instructions = _load_prompt(LLMConfigAgent.PROMPT_MAP.get(mode, LLMConfigAgent.PROMPT_MAP["jump"]))
        return Agent(
            model=model,
            deps_type=AthleteProfile,
            output_type=output_type,
            instructions=instructions,
            retries=1,
            model_settings=default_model_settings(),
        )

    def warmup(self):
        """预热: 用 fresh client 初始化连接。"""

        async def _flow():
            http_client = build_http_client()
            try:
                agent = self._make_agent(http_client, self._mode)
                ctx = AthleteProfile(age=30, weight=70, height=170, level="intermediate")
                await agent.run("OK", deps=ctx, message_history=[])
            finally:
                await http_client.aclose()

        try:
            asyncio.run(_flow())
        except Exception as e:
            print(f"[Warmup] 真实请求预热失败: {e}")

    def _is_config_request(self, user_message: str) -> bool:
        """确定性 fast gate：只识别配置短语或“测试动作 + 参数约束”的组合。"""
        text = user_message.lower()
        if any(phrase in text for phrase in self.STRONG_CONFIG_PHRASES):
            return True
        has_action = any(term in text for term in self.CONFIG_ACTION_TERMS)
        has_constraint = any(term in text for term in self.CONFIG_CONSTRAINT_TERMS)
        return has_action and has_constraint

    def _is_current_config_query(self, user_message: str) -> bool:
        """识别“展示/输出当前配置”类请求，避免误走重新生成配置。"""
        text = user_message.lower()
        has_config_ref = any(term in text for term in self.CONFIG_REFERENCE_TERMS)
        has_query_term = any(term in text for term in self.CURRENT_CONFIG_QUERY_TERMS)
        return has_config_ref and has_query_term

    def _format_current_config_table_markdown(self, config: AnyTestConfig) -> str:
        labels = {
            "test_type": "测试类型",
            "start_type": "启动方式",
            "start_position": "起始位置",
            "stop_type": "停止方式",
            "finish_position": "结束位置",
            "number_of_jumps": "跳跃次数",
            "test_length": "测试时长",
            "starting_foot": "起跳方式",
            "min_contact_time": "最小接触时间(ms)",
            "min_flight_time": "最小腾空时间(ms)",
            "max_flight_time": "最大腾空时间(ms)",
            "metronome_enabled": "节拍器启用",
            "metronome_bpm": "节拍器 BPM",
        }
        rows = [
            "当前建议配置如下：",
            "",
            "| 参数 | 值 |",
            "| --- | --- |",
        ]
        for field_name in config.__dataclass_fields__:
            value = getattr(config, field_name)
            if value is None:
                text = "未设置"
            elif isinstance(value, bool):
                text = "是" if value else "否"
            else:
                text = str(value)
            rows.append(f"| {labels.get(field_name, field_name)} | {text} |")
        return "\n".join(rows)

    def _current_config_query_reply(self) -> str:
        if self._last_config is None:
            return "当前还没有可展示的建议配置，请先说明测试需求生成配置。"
        return self._format_current_config_table_markdown(self._last_config)

    def _cluster_configs(
        self, configs: list,
    ) -> list[list]:
        """按关键字段值聚类 — N 份配置按 (stop_type, jumps, ...) 分组。

        一组 = 需求清晰、LLM 结论一致；多组 = 需求有歧义。
        """
        groups: dict[tuple, list] = {}
        for c in configs:
            key = tuple(getattr(c, f) for f in self._CONSENSUS_FIELDS)
            groups.setdefault(key, []).append(c)
        return list(groups.values())

    def _find_disagreements(
        self, configs: list,
    ) -> dict[str, set]:
        """对比 N 份配置的关键字段，返回不一致的字段及其值集合。

        当前所有字段均为 int/str/Literal，直接用 == 比较。
        若未来新增 float 字段，需改用 math.isclose()。
        """
        disagreements = {}
        for field_name in self._CONSENSUS_FIELDS:
            values = {getattr(c, field_name) for c in configs}
            if len(values) > 1:
                disagreements[field_name] = values
        return disagreements

    def _generate_clarification(self, disagreements: dict[str, set]) -> str:
        """将分歧字段翻译成自然语言追问（模板方式）。"""
        parts = ["我对以下参数不太确定，请您明确一下："]
        for field, values in disagreements.items():
            label = self.FIELD_LABELS.get(field, field)
            vals_str = " 或 ".join(str(v) for v in sorted(str(x) for x in values))
            parts.append(f"- {label}: 应该是 {vals_str}？")
        return "\n".join(parts)

    def _format_config_reply_markdown(
        self,
        config: AnyTestConfig,
        raw_reply: str,
    ) -> str:
        """生成稳定的 Markdown 配置摘要，避免模型把多项设置挤在同一行。"""
        is_ground = config.test_type in {"Sprint and Gait Test", "Overground Running Test"}
        if is_ground and config.stop_type == "Status change":
            stop_label = "单次通过后空场自动结束"
        elif config.stop_type == "End of Time":
            stop_label = f"按测试时长自动停止，共 {config.test_length}"
        elif config.stop_type == "Status change":
            stop_label = f"按跳跃次数自动停止，共 {config.number_of_jumps} 次"
        else:
            stop_label = {
                "Software command": "手动（软件指令）停止",
            }.get(config.stop_type, config.stop_type)
        start_labels = {
            "Status change": "踩上踏板即开始",
        }
        position_labels = {
            "Inside area": "踏板上",
            "Outside area": "踏板外",
        }
        foot_labels = {
            "Not defined": "双脚跳跃",
            "Right": "右脚起跳",
            "Left": "左脚起跳",
        }

        lines = [
            f"为你配置{getattr(config, 'test_type', '测试')}参数，以下是设置总结：",
            "",
            f"- 测试类型：{config.test_type}",
            f"- 停止方式：{stop_label}",
        ]
        if hasattr(config, 'treadmill_speed'):
            lines.append(f"- 跑步机速度：{config.treadmill_speed} km/h")
        if hasattr(config, 'direction'):
            lines.append(f"- 跑步方向：{config.direction}")
        if hasattr(config, 'start_type'):
            lines.append(f"- 启动方式：{start_labels.get(config.start_type, config.start_type)}")
        if is_ground:
            foot_labels = {"Not defined": "未指定", "Left": "左脚", "Right": "右脚"}
            lines.append(f"- 起始脚：{foot_labels[config.starting_foot]}")
        elif hasattr(config, 'starting_foot'):
            lines.append(f"- 起跳方式：{foot_labels.get(config.starting_foot, config.starting_foot)}")
        if hasattr(config, 'start_position'):
            lines.append(f"- 起始位置：{position_labels.get(config.start_position, config.start_position)}")
        if hasattr(config, 'finish_position'):
            lines.append(f"- 结束位置：{position_labels.get(config.finish_position, config.finish_position or '未指定')}")
        lines.extend([
            "",
            ("请先确认配置，进入准备页完成空场自检并核对设备段数后开始。"
             if is_ground else "其他参数已根据默认配置自动设定。准备好了就可以开始测试。"),
        ])
        return "\n".join(lines)

    async def _run_sample(
        self,
        agent: Agent,
        user_message: str,
        ctx: AthleteProfile,
        snapshot: list,
        runtime_ctx: str,
    ):
        """执行一次独立采样，返回 result 与耗时。"""
        t0 = time.perf_counter()
        result = await agent.run(
            user_message,
            deps=ctx,
            message_history=snapshot,
            instructions=runtime_ctx,
        )
        return result, result.output, time.perf_counter() - t0

    async def _run_parallel_samples(
        self,
        agent: Agent,
        user_message: str,
        ctx: AthleteProfile,
        snapshot: list,
        runtime_ctx: str,
        initial_sample: tuple[
            Any,
            Union[
                LLMTestConfig,
                LLMTreadmillGaitConfig,
                LLMTreadmillRunningConfig,
                LLMWalkingConfig,
                LLMOvergroundRunningConfig,
                ChatResponse,
            ],
            float,
        ] | None = None,
    ) -> list[Any]:
        """ClarifyGPT: 从同一个上下文快照并行采样 N 次。"""
        samples: list[Any] = []
        if initial_sample is not None:
            samples.append(initial_sample)

        tasks = [
            self._run_sample(agent, user_message, ctx, snapshot, runtime_ctx)
            for _ in range(self.N_SAMPLES - len(samples))
        ]
        samples.extend(await asyncio.gather(*tasks, return_exceptions=True))
        return samples

    def _resolve_parallel_samples(
        self,
        sample_results: list[Any],
        timing: list[str],
    ) -> tuple[Any | None, str | None, Any | None]:
        """聚类 N 个并行样本，返回配置、追问消息和应写入 history 的 result。"""
        configs: list = []
        config_results: list[tuple] = []
        first_chat_result = None
        first_success_result = None
        failed_count = 0

        for i, item in enumerate(sample_results):
            if isinstance(item, Exception):
                failed_count += 1
                timing.append(f"sample{i+1}=error")
                continue

            result, output, elapsed = item
            if first_success_result is None:
                first_success_result = result
            timing.append(f"sample{i+1}={elapsed:.1f}s")
            print(f"[Timing] 并行采样 sample #{i + 1}: {elapsed:.1f}s")

            if isinstance(output, (LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig)):
                configs.append(output)
                config_results.append((output, result))
            elif isinstance(output, ChatResponse) and first_chat_result is None:
                first_chat_result = result

        history_result = first_chat_result or first_success_result

        if len(configs) < self.MIN_CONFIG_COUNT:
            if first_chat_result is not None:
                return None, first_chat_result.output.message, history_result
            return None, (
                f"信息可能不够充分"
                f"（{len(configs)}/{self.N_SAMPLES} 次采样生成配置，"
                f"{failed_count} 次采样失败）。"
                f"请补充停止方式、跳跃次数或测试时长。"
            ), history_result

        clusters = self._cluster_configs(configs)
        if len(clusters) == 1:
            chosen = clusters[0][0]
            chosen_result = next(
                result for config, result in config_results if config is chosen
            )
            return chosen, None, chosen_result

        disagreements = self._find_disagreements(configs)
        return None, self._generate_clarification(disagreements), history_result

    def _finalize(
        self,
        config: AnyTestConfig | None,
        message: str,
        t_start: float,
        timing: list[str],
        label: str,
        stream_callback: Callable[[str], None] | None = None,
    ) -> tuple[AnyTestConfig | None, str]:
        """统一的收尾：计时 + hint 拼接。消除 ChatResponse/LLMTestConfig/追问 三条分支的重复。"""
        total = time.perf_counter() - t_start
        print(f"[Timing] chat() 总计: {total:.1f}s ({label})")
        hint = f"\n\n⏱ {total:.1f}s ({', '.join(timing)})"
        if stream_callback:
            stream_callback(hint)
        return config, message + hint

    def _finalize_config_output(
        self,
        verified: Union[LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig],
        t_start: float,
        timing: list[str],
        stream_callback: Callable[[str], None] | None = None,
        athlete_profile: AthleteProfile | None = None,
    ) -> tuple[AnyTestConfig | None, str]:
        """将已通过 ClarifyGPT 的 LLM 结构化输出转成系统 Config。"""
        if verified.test_type != MODE_TEST_TYPES[self._mode]:
            return self._finalize(None, "返回的配置与当前测试模式不一致，请重新生成。",
                                  t_start, timing, "模式校验失败", stream_callback)
        config = verified.to_test_config()
        if athlete_profile is not None:
            config = RuleEngine().normalize_runtime_config(config, athlete_profile)
        errors = validate_runtime_config(config)
        if errors:
            return self._finalize(
                None,
                f"配置参数不合法: {'; '.join(errors)}",
                t_start,
                timing,
                "参数校验失败",
                stream_callback,
            )
        self._last_config = config
        normalized_reply = self._format_config_reply_markdown(
            config=config, raw_reply=verified.reply_message,
        )
        if stream_callback:
            stream_callback(normalized_reply)
        return self._finalize(
            config, normalized_reply, t_start, timing, "配置成功", stream_callback,
        )

    async def _process_single_output(
        self,
        output: Union[LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig, ChatResponse],
        t_start: float,
        timing: list[str],
        stream_callback: Callable[[str], None] | None = None,
    ) -> tuple[AnyTestConfig | None, str]:
        """处理单次 LLM 输出，用于非配置 fast path。"""
        if isinstance(output, ChatResponse):
            return self._finalize(None, output.message, t_start, timing, "ChatResponse",
                                  stream_callback)

        if isinstance(output, (LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig)):
            return self._finalize_config_output(
                output, t_start, timing, stream_callback,
            )

        return None, f"未知的输出类型: {type(output).__name__}"

    async def _run_parallel_clarify(
        self,
        agent: Agent,
        user_message: str,
        ctx: AthleteProfile,
        snapshot: list,
        runtime_ctx: str,
        t_start: float,
        timing: list[str],
        stream_callback: Callable[[str], None] | None = None,
        initial_sample: tuple[
            Any,
            Union[
                LLMTestConfig,
                LLMTreadmillGaitConfig,
                LLMTreadmillRunningConfig,
                LLMWalkingConfig,
                LLMOvergroundRunningConfig,
                ChatResponse,
            ],
            float,
        ] | None = None,
    ) -> tuple[AnyTestConfig | None, str]:
        """配置请求路径：N 个样本从同一快照真正并行，随后聚类裁判。"""
        if stream_callback:
            stream_callback("正在生成并校验配置...\n")

        sample_results = await self._run_parallel_samples(
            agent, user_message, ctx, snapshot, runtime_ctx, initial_sample,
        )
        verified, clarify_msg, history_result = self._resolve_parallel_samples(
            sample_results, timing,
        )

        if history_result is not None:
            self.message_history = history_result.all_messages()

        if clarify_msg:
            if stream_callback:
                stream_callback(clarify_msg)
            return self._finalize(
                None, clarify_msg, t_start, timing, "追问", stream_callback,
            )

        return self._finalize_config_output(
            verified, t_start, timing, stream_callback, ctx,
        )

    def chat(
        self, user_message: str, ctx: AthleteProfile
    ) -> tuple[AnyTestConfig | None, str]:
        """
        一轮对话（同步接口，内部用 asyncio.run 统一事件循环以支持并行采样）。

        Returns:
            (config, reply_text):
            - LLM 生成了完整配置: config 有值, reply_text 是配置摘要
            - LLM 自然语言回复/追问: config 为 None, reply_text 是回复内容
        """
        t_start = time.perf_counter()
        timing: list[str] = []
        runtime_ctx = _format_runtime_context(ctx, self._mode)
        snapshot = list(self.message_history or [])

        if self._is_current_config_query(user_message):
            timing.append("local=current-config")
            return self._finalize(
                None,
                self._current_config_query_reply(),
                t_start,
                timing,
                "当前配置查询",
            )

        async def _flow() -> tuple[AnyTestConfig | None, str]:
            http_client = build_http_client()
            try:
                agent = self._make_agent(http_client, self._mode)

                if self._is_config_request(user_message):
                    return await self._run_parallel_clarify(
                        agent, user_message, ctx, snapshot, runtime_ctx, t_start, timing,
                    )

                t0 = time.perf_counter()
                result = await agent.run(
                    user_message,
                    deps=ctx,
                    message_history=snapshot,
                    instructions=runtime_ctx,
                )
                elapsed = time.perf_counter() - t0
                print(f"[Timing] 单次 LLM 调用: {elapsed:.1f}s")

                if isinstance(result.output, (LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig)):
                    timing.append("gate=miss→config-verify")
                    return await self._run_parallel_clarify(
                        agent,
                        user_message,
                        ctx,
                        snapshot,
                        runtime_ctx,
                        t_start,
                        timing,
                        initial_sample=(result, result.output, elapsed),
                    )

                timing.append(f"single={elapsed:.1f}s")
                timing.append("gate=miss→chat")
                self.message_history = result.all_messages()
                return await self._process_single_output(
                    result.output, t_start, timing,
                )
            finally:
                await http_client.aclose()

        try:
            return asyncio.run(_flow())
        except Exception as e:
            print(f"[Timing] chat() 总计: {time.perf_counter() - t_start:.1f}s (失败)")
            return None, f"配置生成失败: {e}"

    def chat_stream(
        self, user_message: str, ctx: AthleteProfile,
        on_chunk: Callable[[str], None],
    ) -> tuple[AnyTestConfig | None, str]:
        """
        流式版 chat()——每收到文本增量即回调 on_chunk(text)。

        用 stream_output() 而非 stream_text()，因为 Union 结构化输出走 tool_call，
        stream_text() 拿不到任何文本。改为监听 partial 对象，从中提取 message/reply_message 增量。
        """
        t_start = time.perf_counter()
        timing: list[str] = []
        runtime_ctx = _format_runtime_context(ctx, self._mode)
        snapshot = list(self.message_history or [])

        if self._is_current_config_query(user_message):
            timing.append("local=current-config")
            reply = self._current_config_query_reply()
            on_chunk(reply)
            return self._finalize(
                None,
                reply,
                t_start,
                timing,
                "当前配置查询",
                stream_callback=on_chunk,
            )

        async def _flow_stream() -> tuple[AnyTestConfig | None, str]:
            http_client = build_http_client()
            try:
                agent = self._make_agent(http_client, self._mode)

                if self._is_config_request(user_message):
                    return await self._run_parallel_clarify(
                        agent, user_message, ctx, snapshot, runtime_ctx,
                        t_start, timing, stream_callback=on_chunk,
                    )

                t0 = time.perf_counter()
                async with agent.run_stream(
                    user_message,
                    deps=ctx,
                    message_history=snapshot,
                    instructions=runtime_ctx,
                ) as result:
                    prev = ""
                    async for partial in result.stream_output(debounce_by=0.05):
                        if isinstance(partial, ChatResponse):
                            current = partial.message or ""
                        elif isinstance(partial, (LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig)):
                            current = ""
                        else:
                            continue
                        if current and len(current) > len(prev):
                            delta = current[len(prev):]
                            on_chunk(delta)
                            prev = current

                    elapsed = time.perf_counter() - t0
                    print(f"[Timing] 单次 LLM 调用(流式): {elapsed:.1f}s")

                    output = await result.get_output()
                    stream_history = result.all_messages()

                if isinstance(output, (LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig)):
                    timing.append("gate=miss→config-verify")
                    return await self._run_parallel_clarify(
                        agent,
                        user_message,
                        ctx,
                        snapshot,
                        runtime_ctx,
                        t_start,
                        timing,
                        stream_callback=on_chunk,
                        initial_sample=(result, output, elapsed),
                    )

                timing.append(f"single={elapsed:.1f}s")
                timing.append("gate=miss→chat")
                self.message_history = stream_history
                return await self._process_single_output(
                    output, t_start, timing, on_chunk,
                )
            finally:
                await http_client.aclose()

        try:
            return asyncio.run(_flow_stream())
        except Exception as e:
            print(f"[Timing] chat_stream() 总计: {time.perf_counter() - t_start:.1f}s (失败)")
            return None, f"配置生成失败: {e}"

    def reset(self):
        """清空对话历史，开始新会话。"""
        self.message_history = None
        self._last_config = None
