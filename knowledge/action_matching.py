"""Finding-specific action applicability and paragraph-level method support."""

import re

from reporting.metric_catalog import METRIC_CATALOG


MATCHING_VERSION = "finding-action-evidence/1.0"
PROTOCOLS = {
    "Jump Test": ("vertical_jump",),
    "Treadmill Gait Test": ("treadmill_walk",),
    "Treadmill Running Test": ("treadmill_run",),
    "Sprint and Gait Test": ("overground_walk",),
    "Overground Running Test": ("overground_run", "treadmill_and_overground_run"),
}
METRIC_TERMS = {
    "jump_height_m": r"\b(?:jump height|vertical jump height|jumping height)\b|跳跃高度|纵跳高度",
    "air_time_s": r"\b(?:flight time|air time)\b|腾空时间",
    "flight_time_s": r"\bflight time\b|腾空时间",
    "contact_time_s": r"\b(?:ground contact time|contact time)\b|触地时间",
    "cadence_steps_per_min": r"\b(?:step rate|step frequency|stride frequency|cadence)\b|步频",
    "step_length_cm": r"(?<![a-z])step length\b|步长",
    "step_length_m": r"(?<![a-z])step length\b|步长",
    "stride_length_cm": r"\bstride length\b|步幅",
    "stride_length_m": r"\bstride length\b|步幅",
    "step_time_s": r"\bstep time\b|步时",
    "gait_cycle_s": r"\b(?:gait cycle|stride time)\b|步态周期",
    "speed_m_s": r"\b(?:walking speed|running speed|gait speed|velocity)\b|步速",
}
METRIC_TERMS["cadence_steps_per_s"] = METRIC_TERMS["cadence_steps_per_min"]
_METRIC_UNITS = (("cadence_steps_per_min", "cadence_steps_per_s"),
                 ("step_length_cm", "step_length_m"), ("stride_length_cm", "stride_length_m"))


def literature_metrics(metric):
    """Match the measured quantity across literature units without converting report values."""
    return next((codes for codes in _METRIC_UNITS if metric in codes), (metric,))


_RESULT = re.compile(r"agreement|reliab|repeatab|intraclass|\bICC|\bCVME|coefficient of variation|limits of agreement|standard deviation|variability|一致性|信度|变异", re.I)
_METHOD = re.compile(r"calculated|measured|recorded|averaged|analy[sz]ed|repeated|test.retest|计算|测量|记录|复测", re.I)
_LIMITATION = re.compile(r"bias|error|limit|overestimat|underestimat|误差|偏差|限制", re.I)
_UNSUITABLE = re.compile(r"\b(?:purpose|aim|objective)\b|injury|patient|pain|rehabilitation|reduce.*risk|目的|诊断|损伤|患者", re.I)

# Each finding has alternatives. A concrete limitation is required for limitation_review.
ACTION_SPECS = {
    "compare_segments": {"types": ("temporal_change",), "category": "coach_review", "priority": 0,
        "focus": "前后分段的均值、差值方向和变化幅度", "support": ("agreement", "method"),
        "text": "复核{metric}的前后分段均值、差值方向和变化幅度，并沿记录顺序定位变化位置。"},
    "track_change": {"types": ("temporal_change", "verified_change"), "category": "retest", "priority": 1,
        "focus": "同口径复测后比较变化方向与幅度", "support": ("agreement", "repeatability", "method"),
        "text": "按相同测试条件和分组口径复测{metric}，对照本次记录的变化方向与幅度，观察是否重复出现。"},
    "compare_sides": {"types": ("side_difference",), "category": "coach_review", "priority": 0,
        "focus": "分别核对左右值及原证据定义的侧别差异", "support": ("side_method", "agreement"),
        "text": "分别核对左右侧{metric}与原分组定义，比较两侧数值及差值方向；对照原记录中的对称性指标。"},
    "retest_sides": {"types": ("side_difference",), "category": "retest", "priority": 1,
        "focus": "同侧前后复测，保留左右分组与差值口径", "support": ("side_method", "repeatability"),
        "text": "在相同条件下分别复测左右侧{metric}，按同侧前后对照，检查左右差异方向与幅度是否重复出现。"},
    "check_repeatability": {"types": ("variability",), "category": "retest", "priority": 0,
        "focus": "离散程度与重复测试一致性", "support": ("repeatability",),
        "text": "复测时保留各次{metric}记录，核对可用的离散程度指标，并沿用相同统计口径检查重复测试一致性。"},
    "explain_limitation": {"types": ("measurement_limitation",), "category": "measurement_review", "priority": 0,
        "focus": "具体质量限制对该结果可解释范围的影响", "support": ("limitation", "method"),
        "text": "本次{metric}记录的具体限制为{limitation}。{impact}复核受影响记录，并在满足条件后重新计算或复测。"},
    "check_conditions": {"types": ("conditions_review",), "category": "measurement_review", "priority": 0,
        "focus": "核对已要求复核的测试条件", "support": ("method",),
        "text": "核对{metric}对应的测试条件记录，后续比较沿用同一设备、动作方式及分组口径。"},
}
_LIMIT_LABELS = {"insufficient_sample_size": "有效样本不足", "quality_invalidation": "该指标存在质量失效记录",
                 "report_quality_invalidates_analysis": "报告质量标记使分析失效"}
_LIMIT_IMPACTS = {"insufficient_sample_size": "当前样本量不足以支持对应分组比较。",
                  "quality_invalidation": "受影响记录无法作为该指标比较的有效依据。",
                  "report_quality_invalidates_analysis": "该质量状态下无法解释本次分析结论。"}


def concrete_limitations(claim):
    return tuple(value for value in claim.limitations if value and value != "co_change_is_not_causation")


def action_candidates(context, claim):
    if context.test_type not in PROTOCOLS or not set(claim.metric_codes).intersection(context.metric_codes):
        return ()
    return tuple(action_id for action_id, spec in ACTION_SPECS.items()
                 if claim.finding_type in spec["types"]
                 and (action_id != "explain_limitation" or concrete_limitations(claim)))


def paragraph_support(text, metric):
    """Return exact sentences with direct metric/method support, never paper-wide tags."""
    pattern = METRIC_TERMS.get(metric)
    if pattern is None:
        return ()
    matches = []
    for sentence in re.split(r"(?<=[.!?。])\s+(?=[A-Z\u3400-\u9fff])", text):
        sentence = sentence.strip()
        if not re.search(pattern, sentence, re.I) or _UNSUITABLE.search(sentence):
            continue
        supports = []
        if _RESULT.search(sentence) and not re.search(r"shown in Figure|presented in Table|purpose|aim", sentence, re.I):
            supports.append("agreement")
        if re.search(r"test.retest|repeatab|repeated|reliab|variability|standard deviation|coefficient of variation|复测|重复|变异|标准差", sentence, re.I):
            supports.append("repeatability")
        if _METHOD.search(sentence):
            supports.append("method")
        if re.search(r"left|right|\bLt\.|\bRt\.|bilateral|symmetr|左右|左侧|右侧|对称", sentence, re.I) and (_METHOD.search(sentence) or _RESULT.search(sentence)):
            supports.append("side_method")
        if _LIMITATION.search(sentence):
            supports.append("limitation")
        if supports:
            matches.append({"excerpt": sentence, "support": tuple(supports),
                            "priority": 0 if "agreement" in supports else 1})
    return tuple(sorted(matches, key=lambda item: item["priority"]))


def sentence_protocol_matches(sentence, test_type):
    if test_type in {"Treadmill Running Test", "Overground Running Test"}:
        if re.search(r"\bwalk(?:ing)?\b", sentence, re.I) and not re.search(r"\brun(?:ning)?\b", sentence, re.I):
            return False
    if test_type in {"Treadmill Gait Test", "Sprint and Gait Test"}:
        if re.search(r"\brun(?:ning)?\b", sentence, re.I) and not re.search(r"\bwalk(?:ing)?\b", sentence, re.I):
            return False
    return True


def evidence_action_match(context, claim, metric, action_id, evidence):
    if action_id not in action_candidates(context, claim) or metric not in claim.metric_codes:
        return None
    spec = ACTION_SPECS[action_id]
    domain = {"Jump Test": "jump", "Treadmill Gait Test": "walk", "Treadmill Running Test": "run",
              "Sprint and Gait Test": "walk", "Overground Running Test": "run"}.get(context.test_type)
    if (evidence.domain != domain or not evidence.recommendation_allowed
            or not set(literature_metrics(metric)).intersection(evidence.metric_codes) or context.population not in evidence.populations
            or not {"method", "interpretation", "limitation"}.intersection(evidence.support_types)):
        return None
    protocol = evidence.metadata.get("protocol")
    same_protocol = protocol in PROTOCOLS.get(context.test_type, ())
    # Separate recording of left/right is transferable across walking surfaces;
    # device-error thresholds and repeatability estimates are not transferred.
    side_record_transfer = (context.test_type == "Treadmill Gait Test" and protocol == "overground_walk"
                            and action_id == "compare_sides")
    if not same_protocol and not side_record_transfer:
        return None
    for match in paragraph_support(evidence.excerpt, metric):
        if not sentence_protocol_matches(match["excerpt"], context.test_type):
            continue
        supports = set(match["support"])
        if not supports.intersection(spec["support"]):
            continue
        if side_record_transfer and "side_method" not in supports:
            continue
        return {
            "evidence_id": evidence.evidence_id, "metric_code": metric, "action_id": action_id,
            "excerpt": match["excerpt"], "support": list(match["support"]),
            "protocol": protocol,
            "applicability": "same_protocol_method" if same_protocol else "side_recording_only_across_walk_surfaces",
            "reason": ("段落直接讨论该指标，支持" + spec["focus"] + "的方法学复核。"
                       + ("只迁移左右分别记录的方法，不迁移地面步行的阈值、误差或信度数值。" if side_record_transfer else "")
                       + "本次发现的成立依据来自测试证据。"),
        }
    return None


def finding_summary(claim, metric):
    """Use only validated numeric fields, with their original units and grouping."""
    if claim.data_origin != "validated_report":
        return ""
    parts = []
    for item in claim.evidence:
        if metric not in item.metric_codes:
            continue
        keys = {
            "verify_temporal_change": (("first_mean", "前半均值"), ("second_mean", "后半均值"), ("difference", "后减前")),
            "verify_side_segment_difference": (("left_change", "左侧后减前"), ("right_change", "右侧后减前")),
            "verify_cross_metric_cochange": ((f"{metric}_first_mean", "前半均值"), (f"{metric}_second_mean", "后半均值"), (f"{metric}_difference", "后减前")),
            "compare_session_records": ((f"{metric}_previous_mean", "上次均值"), (f"{metric}_current_mean", "本次均值"), (f"{metric}_difference", "本次减上次")),
            "summarize_records": ((f"{metric}_mean", "均值"), (f"{metric}_std", "总体标准差")),
        }.get(item.analysis_method, ())
        values = [f"{label} {item.numeric_values[key]:.12g} {item.numeric_units[key]}"
                  for key, label in keys if key in item.numeric_values and key in item.numeric_units]
        if values:
            from reporting.charts import GROUP_LABELS
            labels = {**GROUP_LABELS, "current": "本次", "previous": "上次"}
            counts = [f"{labels[group]}样本 {count} 条" for group, count in item.sample_counts.items() if group in labels]
            values.extend(counts)
            parts.append("，".join(values))
    return "；".join(parts) + "。" if parts else ""


def render_action(context, claim, metric, action_id):
    label = METRIC_CATALOG[metric].label
    limitation = "、".join(_LIMIT_LABELS.get(value, value) for value in concrete_limitations(claim))
    impact = "".join(dict.fromkeys(_LIMIT_IMPACTS.get(value, "") for value in concrete_limitations(claim)))
    text = ACTION_SPECS[action_id]["text"].format(metric=label, limitation=limitation, impact=impact)
    if action_id == "compare_sides" and not any("symmetry" in key or "asymmetry" in key
                                               for item in claim.evidence for key in item.numeric_values):
        text = text.replace("；对照原记录中的对称性指标", "")
    conditions = ""
    if action_id in {"track_change", "retest_sides", "check_repeatability", "check_conditions"}:
        speed = context.test_conditions.get("treadmill_speed")
        if isinstance(speed, (int, float)) and not isinstance(speed, bool):
            conditions = f"本次跑带速度设置为 {speed:.12g} km/h。"
    return finding_summary(claim, metric) + conditions + text
