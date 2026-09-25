"""Only complete imperative utterances can mutate a test session."""

import re


_COMMANDS = {
    "interrupt": ("等一下", "等会儿", "先别说", "别说了", "停止播报", "打住"),
    "start": ("开始", "开始测试", "开始采集", "开始吧"),
    "pause": ("暂停", "暂停测试", "暂停一下", "先暂停", "暂停采集"),
    "resume": ("继续", "继续测试", "继续采集", "恢复测试", "继续吧"),
    "stop": ("结束", "结束测试", "停止测试", "停止采集", "停止", "停止吧"),
    "prepare": ("准备测试", "进入测试准备", "准备就绪"),
    "confirm": ("确认配置", "应用配置", "确认测试配置"),
    "report": ("分析报告", "分析测试报告", "解读报告", "查看报告"),
    "setup": ("返回配置", "重新配置", "返回首页"),
}
_LOOKUP = {phrase: command for command, phrases in _COMMANDS.items() for phrase in phrases}


def normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?]", "", text)


def match_command(text: str) -> str | None:
    text = normalize(text)
    for prefix in ("请帮我", "帮我", "请"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return _LOOKUP.get(text)


def is_filler(text: str) -> bool:
    return normalize(text) in {"", "嗯", "呃", "啊", "哦", "唔"}


def conversational_reply(text: str) -> str | None:
    """Small, exact social intents; never interpret these as test commands."""
    value = normalize(text).lower()
    if re.fullmatch(r"(?:喂|嘿|你好|您好|哈喽|嗨|豆包)*(?:你是谁|你叫什么|你叫什么名字|你是豆包吗)", value):
        return "我是 Iron Jump 的语音助手，使用豆包语音识别和播报，可以帮你控制测试、解读步态报告。"
    if re.fullmatch(r"(?:喂|嘿|你好|您好|哈喽|嗨|豆包|在吗|你在吗|hello|hi)+", value):
        return "你好，我在。可以帮你控制测试和解读步态报告。"
    if value in {"能听到吗", "能听见吗", "你能听到我说话吗", "听得到吗"}:
        return "收到了你的语音。可以说准备测试、开始、暂停、继续或结束测试。"
    if value in {"你能做什么", "你会什么", "怎么使用", "怎么用", "帮助"}:
        return "我可以控制测试的开始、暂停、继续和结束。打开步态报告后，还可以问左右脚差异、步频稳定性和前后半程变化。"
    if value in {"谢谢", "谢谢你", "好的谢谢"}:
        return "不客气，我在。"
    return None
