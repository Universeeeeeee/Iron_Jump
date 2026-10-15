"""
diagnose_latency.py — Agent 延迟诊断工具

逐步拆解 agent.run() 的完整耗时，定位瓶颈：
  1. 纯 text completion（无 tool，无 structured output）→ 测量模型基础推理延迟
  2. Structured output（Union type，有 tools）→ 测量 pydantic-ai 工具调用开销
  3. 检查 thinking 是否真正被禁用
  4. 检查是否存在额外的 tool call 轮次

用法:
    conda run -n pydantic_ai python -m agent.diagnose_latency
"""

from __future__ import annotations

import asyncio
import time
import os
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv
from typing import Union

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from agent.models import AthleteProfile, LLMTestConfig, ChatResponse

# ---- Init ----
dotenv_path = _project_root / '.env'
load_dotenv(dotenv_path=dotenv_path)

base_url = os.getenv("OPENAI_BASE_URL")
api_key = os.getenv("OPENAI_API_KEY")
print(f"API: {base_url}")
print(f"Model: deepseek-v4-flash")
print()

# ---- Test 1: 纯文本调用 (无 structured output, 无 tools) ----
async def test_plain_text():
    """最简单的 API 调用：纯文本，无任何工具或结构化输出"""
    model = OpenAIChatModel(
        'deepseek-v4-flash',
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )
    agent = Agent(
        model=model,
        instructions="用一句话回复用户。",
        model_settings={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    print("=" * 60)
    print("Test 1: 纯文本调用 (无 tool, 无 structured output)")
    t0 = time.perf_counter()
    result = await agent.run("你好，请说你好")
    elapsed = time.perf_counter() - t0
    print(f"  耗时: {elapsed:.1f}s")
    print(f"  回复: {result.output}")
    msgs = result.all_messages()
    print(f"  消息轮次: {len(msgs)}")
    for i, msg in enumerate(msgs):
        print(f"    [{i}] {type(msg).__name__}: {str(msg)[:200]}")
    print()
    return elapsed


# ---- Test 2: Structured Output (Union type, 有 tools) ----
async def test_structured_output():
    """带 structured output + 工具的完整调用（模拟实际 chat 场景）"""
    model = OpenAIChatModel(
        'deepseek-v4-flash',
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )
    agent = Agent(
        model=model,
        deps_type=AthleteProfile,
        output_type=Union[LLMTestConfig, ChatResponse],  # type: ignore
        instructions=SYSTEM_PROMPT,
        retries=1,
        model_settings={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    @agent.tool
    def get_patient_history(ctx: RunContext[AthleteProfile]) -> str:
        return "无历史记录"

    @agent.tool
    def get_device_capabilities(ctx: RunContext[AthleteProfile]) -> str:
        return "设备通道数: 8\n采样率: 1000Hz\n测试类型: Jump Test"

    ctx = AthleteProfile(age=70, weight=65, height=165, level="beginner")

    print("=" * 60)
    print("Test 2: Structured Output + Tools (模拟实际场景)")
    t0 = time.perf_counter()
    result = await agent.run(
        "入门用户，做5次跳跃测试",
        deps=ctx,
    )
    elapsed = time.perf_counter() - t0
    print(f"  总耗时: {elapsed:.1f}s")
    print(f"  输出类型: {type(result.output).__name__}")

    # 分析消息轮次
    msgs = result.all_messages()
    print(f"  消息轮次: {len(msgs)}")
    api_calls = 0
    for i, msg in enumerate(msgs):
        t = type(msg).__name__
        if t == "ModelRequest":
            api_calls += 1
            print(f"    [{i}] >>> API Request #{api_calls} <<<")
        elif t == "ModelResponse":
            # 检查 response 内容
            parts_info = []
            for part in msg.parts:
                pt = type(part).__name__
                if pt == "ToolCallPart":
                    parts_info.append(f"ToolCall({part.tool_name})")
                elif pt == "TextPart":
                    parts_info.append(f"Text({str(part.content)[:80]})")
                else:
                    parts_info.append(pt)
            print(f"    [{i}] ModelResponse: {', '.join(parts_info)}")
        elif t == "ToolReturnPart":
            print(f"    [{i}] ToolReturn({msg.tool_name}): {str(msg.content)[:100]}")
        else:
            print(f"    [{i}] {t}")

    print(f"  API 调用次数: {api_calls}")
    print(f"  说明: 每次 Request→Response 是一次完整的 HTTP 往返")
    print()
    return elapsed


# ---- Test 3: 仅 ChatResponse (无 tool call 场景) ----
async def test_chat_only():
    """仅自然语言回复，不走 structured output"""
    model = OpenAIChatModel(
        'deepseek-v4-flash',
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )
    agent = Agent(
        model=model,
        deps_type=AthleteProfile,
        output_type=Union[LLMTestConfig, ChatResponse],  # type: ignore
        instructions=SYSTEM_PROMPT,
        retries=1,
        model_settings={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    @agent.tool
    def get_patient_history(ctx: RunContext[AthleteProfile]) -> str:
        return "无历史记录"

    @agent.tool
    def get_device_capabilities(ctx: RunContext[AthleteProfile]) -> str:
        return "设备通道数: 8\n采样率: 1000Hz"

    ctx = AthleteProfile(age=25, weight=70, height=175, level="intermediate")

    print("=" * 60)
    print("Test 3: 纯闲聊 (期望 ChatResponse, 不走 tool call)")
    t0 = time.perf_counter()
    result = await agent.run("你好，介绍一下你自己", deps=ctx)
    elapsed = time.perf_counter() - t0
    print(f"  总耗时: {elapsed:.1f}s")
    print(f"  输出类型: {type(result.output).__name__}")
    if isinstance(result.output, ChatResponse):
        print(f"  回复: {result.output.message[:200]}")
    msgs = result.all_messages()
    api_calls = sum(1 for m in msgs if isinstance(m, ModelRequest))
    print(f"  API 调用次数: {api_calls}")
    print()
    return elapsed


# ---- Test 4: thinking 禁用 vs 启用对比 ----
async def test_thinking_comparison():
    """对比 thinking 启用/禁用的延迟差异"""
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print("=" * 60)
    print("Test 4: thinking 禁用 vs 启用 延迟对比")

    # 4a: thinking disabled
    body_disabled = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "say: hello"}],
        "max_tokens": 100,
        "thinking": {"type": "disabled"},
    }

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=body_disabled,
        )
    elapsed_disabled = time.perf_counter() - t0
    data = resp.json()
    usage_disabled = data.get("usage", {})
    content_disabled = data["choices"][0]["message"].get("content", "")
    reasoning_disabled = data["choices"][0]["message"].get("reasoning_content", "")
    print(f"  4a) thinking=disabled: {elapsed_disabled:.1f}s, "
          f"tokens={usage_disabled.get('total_tokens')}, "
          f"content='{content_disabled[:50]}', "
          f"reasoning_len={len(reasoning_disabled)}")

    # 4b: thinking enabled (default)
    body_enabled = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "say: hello"}],
        "max_tokens": 100,
    }

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=body_enabled,
        )
    elapsed_enabled = time.perf_counter() - t0
    data = resp.json()
    usage_enabled = data.get("usage", {})
    content_enabled = data["choices"][0]["message"].get("content", "")
    reasoning_enabled = data["choices"][0]["message"].get("reasoning_content", "")
    print(f"  4b) thinking=enabled(default): {elapsed_enabled:.1f}s, "
          f"tokens={usage_enabled.get('total_tokens')}, "
          f"content='{content_enabled[:50]}', "
          f"reasoning_len={len(reasoning_enabled)}")

    ratio = elapsed_enabled / elapsed_disabled if elapsed_disabled > 0 else 0
    print(f"  结论: thinking 启用比禁用慢 {ratio:.1f}x "
          f"(+{elapsed_enabled - elapsed_disabled:.1f}s)")
    print()
    return elapsed_disabled, elapsed_enabled


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT (复制自 llm_agent.py)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
你是 IronJump 步态分析系统的参数配置助手。回复使用 Markdown 格式。
你有两种回复方式：
1. ChatResponse — 自然语言：打招呼、解释参数、追问
2. LLMTestConfig — 结构化配置：用户给出足够测试需求时生成

决策规则：
- 闲聊/打招呼 → ChatResponse
- 需求不具体 → ChatResponse 追问
- 明确测试需求后 → LLMTestConfig，reply_message 中解释配置

❗ 宁可多问，不要猜测。必要参数（如停止方式、跳跃次数）必须从用户处明确获得。

配置情景指引：
- 用户说"跳N次" → stop_type="Status change"
- 用户说"测X分钟" → stop_type="End of Time"
- 未指定停止条件 → 追问跳跃次数或测试时长
- 纵跳模式默认双脚起跳，starting_foot="Not defined"，reply_message 中说"双脚跳跃"不要写"未指定"

沉默规则：
底层滤波参数（min_contact_time, min_flight_time, max_flight_time）由 LLM 根据用户信息自动设置，
不要在 reply_message 中提及、解释或展示这些参数，除非用户主动追问。

触发值（静默设置，不向用户解释）：
- 年长用户(>60): min_contact_time>=80, number_of_jumps<=3
- 入门用户: min_contact_time>=100, number_of_jumps<=3
- 儿童(<12): min_contact_time>=40
- 采样率硬件固定 1000Hz
"""


async def main():
    from pydantic_ai.messages import ModelRequest

    results = {}

    # Test 1: 纯文本
    try:
        results['plain_text'] = await test_plain_text()
    except Exception as e:
        print(f"Test 1 失败: {e}\n")

    # Test 4: thinking 对比
    try:
        t_disabled, t_enabled = await test_thinking_comparison()
        results['thinking_disabled'] = t_disabled
        results['thinking_enabled'] = t_enabled
    except Exception as e:
        print(f"Test 4 失败: {e}\n")
        import traceback
        traceback.print_exc()

    # Test 3: 纯闲聊
    try:
        results['chat_only'] = await test_chat_only()
    except Exception as e:
        print(f"Test 3 失败: {e}\n")
        import traceback
        traceback.print_exc()

    # Test 2: Structured output
    try:
        results['structured'] = await test_structured_output()
    except Exception as e:
        print(f"Test 2 失败: {e}\n")
        import traceback
        traceback.print_exc()

    # ---- 总结 ----
    print("=" * 60)
    print("总结")
    print("-" * 40)
    for name, elapsed in results.items():
        print(f"  {name}: {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
