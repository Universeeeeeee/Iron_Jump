"""Versioned Report Agent prompt resources."""

import hashlib
from pathlib import Path


PROMPT_VERSION = "report-agent-system/2.0"
SEQUENTIAL_PROMPT_VERSION = "report-agent-sequential-system/3.1"

QUESTION_PLAN_INSTRUCTIONS = (
    "将用户对当前运动报告的追问解析为 ReportQuestionPlan。只选择目录中的 record_set_id 和 metric_codes。"
    "最多选择两个指标。默认继承 previous 范围。用户说‘再看左侧’时保留原范围并筛选 side。"
    "若上轮已筛选一侧而用户改问另一侧，使用 scope_basis=report，"
    "依据上文 selection.label 和 prior_turns 重建同一半程、时间或记录序号范围，再设置新 side。"
    "‘前半程/后半程’默认以完整报告有效记录数量分半，scope_basis=report；"
    "只有明确说‘其中再分半’才在 previous 内再次分半。保持指标级有效样本和原始顺序。"
    "记录序号从1开始，start_record/end_record和时间范围两端均包含。"
    "仅更换已有图形样式时使用 intent=chart，系统完整继承 previous 的记录和指标，"
    "segment/side 使用 all，序号和时间界限使用 null，选择 chart_type。"
    "若用户同时改变范围或指标并要求画图，使用 intent=analyze 配合 chart_type。"
    "追问原因或依据时选择 explain 并针对所选发现的指标。"
    "当前追问选择有效纳入记录。若问题要求比较纳入与排除记录的稳健性，"
    "intent=clarify，clarification说明可在完整报告分析中查看排除稳健性。"
    "当用户请求历史数据或问题无法匹配可用数据时，intent=clarify，clarification写具体需补充的信息。"
    "返回结构化计划。"
)
QUESTION_PLAN_TEMPLATE = "问题：{question}\n上文：{parent_context}\n当前报告：{observation}"
QUESTION_DECISION_TEMPLATE = (
    "本轮回答 question_context.question。系统已固定 selection 的记录范围，"
    "根据已有 summarize_records 结果判断是否还需验证变化。仅选择 selection 中的记录集和指标，"
    "record_refs 由系统注入。问答可直接用范围统计回答，即使指标平稳也应回答用户所问。"
    "前后变化是选定范围内再次按有效记录数量分半，须明确该口径。"
    "intent=chart 时系统优先按父证据的方法复现分组，已有证据图所需结果后直接停止。"
)
QUESTION_SYNTHESIS_TEMPLATE = (
    "仅回答 question_context.question，优先使用所选范围的 summarize_records 证据。"
    "当该证据 comparison_supported=true 时，至少给出一条绑定该证据的 derived Claim。"
    "局部追问的数值使用当前工具证据，fact_refs 置空。解释所选发现时说明指标、实际分组和记录依据。"
    "NumericBinding.value_key 可引用 numeric_values 或 sample_counts 中的原始键名。"
    "limitations 仅引用当前工具证据的实际限制，范围由界面显示。"
    "省略未查询历史、未做其他比较或无关指标缺失等通用免责声明。"
    "intent=chart 时优先引用已复现父图分组的证据与支持的谓词，保留原始分组口径。"
)

DECISION_STAGE_TEMPLATE = (
    "阶段：Sequential Decision。基于最新状态只选择下一项动作或正常停止。"
)
PLAN_STAGE_TEMPLATE = (
    "阶段：Initial Observation。请提出最多3个值得确定性验证的问题和小型计划。"
)
REVIEW_STAGE_TEMPLATE = (
    "阶段：Evidence Review。判断证据是否足够；只有冲突、质量限制或明确未解决问题时才给出一次Replan。"
)
SYNTHESIS_STAGE_TEMPLATE = (
    "阶段：Structured Synthesis。只生成绑定Fact/Evidence的Claim。"
    "Claim文本中的数值必须使用NumericBinding占位符。"
)
SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE = (
    "阶段：Sequential Structured Synthesis。只生成绑定Fact/Evidence的Claim。"
    "Claim文本中的数值必须使用NumericBinding占位符。"
)
REPAIR_STAGE_TEMPLATE = (
    "阶段：Structured Output Repair。确定性Validator拒绝了Draft。"
    "只修正引用、Claim类型、PredicateBinding或NumericBinding；"
    "不得增加新发现、数值或Evidence。"
)


def load_system_prompt() -> str:
    return (Path(__file__).resolve().parent / "system.md").read_text(
        encoding="utf-8"
    ).strip()


def load_sequential_system_prompt() -> str:
    return (Path(__file__).resolve().parent / "sequential_system.md").read_text(
        encoding="utf-8"
    ).strip()


def prompt_content_digest(*components: str) -> str:
    payload = "\x1f".join(component.strip() for component in components)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def readable_prompt_version(base_version: str, digest: str) -> str:
    return f"{base_version}#{digest[:12]}"
