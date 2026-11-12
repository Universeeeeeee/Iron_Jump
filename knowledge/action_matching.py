"""Finding-specific action applicability and paragraph-level method support."""

import re
import math

from reporting.metric_catalog import METRIC_CATALOG


MATCHING_VERSION = "finding-action-evidence/2.1"
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

# Data follow-ups use only verified session evidence. Literature actions require
# an explicit, reviewed action-support annotation on the cited paragraph.
ACTION_SPECS = {
    "track_change": {"types": ("temporal_change", "verified_change"), "category": "retest", "priority": 0,
        "basis": "data", "focus": "后续同协议测试中追踪已验证变化的方向与幅度", "support": (),
        "text": "在后续同协议测试中继续追踪{metric}的这一变化，并结合动作执行记录观察其重复性。"},
    "track_side_changes": {"types": ("side_temporal_change",), "category": "retest", "priority": 0,
        "basis": "data", "focus": "追踪左右两侧各自的前后变化及变化幅度差别", "support": (),
        "text": "后续同协议测试中分别追踪左右侧{metric}各自的前后段变化，观察两侧变化幅度的差别是否重复出现。"},
    "check_repeatability": {"types": ("temporal_change", "verified_change", "side_temporal_change"), "category": "retest", "priority": 0,
        "basis": "literature", "focus": "文献直接支持的重复测试方法", "support": ("repeatability",),
        "text": "依照所引研究直接支持的复测方法，保留各次{metric}记录，并沿用相同统计口径观察重复测试一致性。"},
    "explain_limitation": {"types": ("measurement_limitation",), "category": "measurement_review", "priority": 0,
        "basis": "data", "focus": "本次证据记录的具体限制及解释范围", "support": (),
        "text": "本次{metric}记录的具体限制为{limitation}。{impact}满足对应条件后再比较或复测。"},
    "check_conditions": {"types": ("conditions_review",), "category": "measurement_review", "priority": 0,
        "basis": "literature", "focus": "文献直接支持的测试条件记录方法", "support": ("method",),
        "text": "按所引文献直接支持的方法记录{metric}对应的测试条件，供后续同协议比较使用。"},
}
UNSUPPORTED_FINDINGS = {
    "side_difference": "当前行动链路尚未接入左右水平差异的确定性验证算子。",
    "variability": "当前行动链路尚未接入离散程度变化的确定性验证算子。",
}
_LIMIT_LABELS = {"insufficient_sample_size": "有效样本不足", "quality_invalidation": "该指标存在质量失效记录",
                 "report_quality_invalidates_analysis": "报告质量标记使分析失效"}
_LIMIT_IMPACTS = {"insufficient_sample_size": "当前样本量不足以支持对应分组比较。",
                  "quality_invalidation": "受影响记录无法作为该指标比较的有效依据。",
                  "report_quality_invalidates_analysis": "该质量状态下无法解释本次分析结论。"}


def concrete_limitations(claim):
    return tuple(value for value in claim.limitations if value in _LIMIT_LABELS or
                 (value.partition(":")[0] in {"left", "right"} and value.partition(":")[2] in _LIMIT_LABELS))


def action_candidates(context, claim):
    if (claim.finding_type in UNSUPPORTED_FINDINGS or context.test_type not in PROTOCOLS
            or not set(claim.metric_codes).intersection(context.metric_codes)):
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


def _verified_limitation(context, claim, metric, item):
    """Validate a tool's failed comparison or quality assessment independently of change evidence."""
    limitations = tuple(value for value in concrete_limitations(claim) if value in item.limitations)
    expected_status = "conclusive" if item.analysis_method == "quality_scope_check" else "inconclusive"
    if (item.analysis_status != expected_status or not limitations
            or item.analysis_method not in {"verify_temporal_change", "verify_cross_metric_cochange",
                "verify_side_segment_difference", "verify_exclusion_robustness", "summarize_records", "quality_scope_check"}):
        return False
    if not any(p.get("predicate") == "comparison_supported" and p.get("supported") is False
               and p.get("predicate_evidence_id")
               and (metric in p.get("metric_codes", ()) or item.analysis_method == "quality_scope_check")
               for p in item.limitation_assessments):
        return False
    sample_limits = [value for value in limitations if value.endswith("insufficient_sample_size")]
    for limitation in sample_limits:
        from reporting.kernel import MIN_COMPARISON_GROUP_SIZE
        side = limitation.partition(":")[0] if ":" in limitation else None
        required = {
            "verify_temporal_change": ("first_half", "second_half"),
            "verify_cross_metric_cochange": ("first_half", "second_half"),
            "summarize_records": ("selected",),
            "verify_exclusion_robustness": ("all_first", "all_second", "included_first", "included_second"),
            "verify_side_segment_difference": (f"{side}_first", f"{side}_second"),
        }.get(item.analysis_method)
        if required is None:
            return False
        minimum = 1 if item.analysis_method == "summarize_records" else MIN_COMPARISON_GROUP_SIZE
        if not all(group in item.record_groups and len(item.record_groups[group]) == item.sample_counts.get(group)
                   and len(set(item.record_groups[group])) == len(item.record_groups[group]) for group in required):
            return False
        if not any(item.sample_counts[group] < minimum for group in required):
            return False
    flags = [flag for flag in context.quality_evidence if flag.get("quality_flag_id") in item.quality_flag_refs]
    if any(value.endswith("quality_invalidation") for value in limitations) and not any(
        flag.get("invalidates_report") or metric in flag.get("invalidates_metric_codes", ()) for flag in flags
    ):
        return False
    if "report_quality_invalidates_analysis" in limitations and not any(flag.get("invalidates_report") for flag in flags):
        return False
    return True


def verified_finding_evidence(context, claim, metric):
    """Require structured, snapshot-bound evidence; prose and origin labels are insufficient."""
    if (claim.data_origin != "validated_report" or metric not in claim.metric_codes
            or metric not in context.metric_codes or metric not in METRIC_CATALOG):
        return ()
    accepted = []
    for item in claim.evidence:
        if (item.package_digest != context.package_digest or not item.evidence_id or not item.tool_run_id
                or (metric not in item.metric_codes and item.analysis_method != "quality_scope_check")):
            continue
        if claim.finding_type == "measurement_limitation":
            if _verified_limitation(context, claim, metric, item):
                accepted.append(item)
            continue
        if item.analysis_status != "conclusive":
            continue
        predicates = {p.get("predicate") for p in item.predicates
                      if p.get("supported") is True and p.get("predicate_evidence_id")
                      and metric in p.get("metric_codes", ())}
        if not predicates or not item.numeric_values or not item.record_groups:
            continue
        if any(not math.isfinite(value) for value in item.numeric_values.values()):
            continue
        if any(len(refs) != item.sample_counts.get(group) or not refs or len(set(refs)) != len(refs)
               for group, refs in item.record_groups.items()):
            continue
        method = item.analysis_method
        if method == "verify_side_segment_difference":
            valid = (claim.finding_type == "side_temporal_change" and "concentrated_on_side" in predicates
                     and {"left_change", "right_change"}.issubset(item.numeric_values)
                     and {"left_change", "right_change"}.issubset(item.numeric_units)
                     and {"left_first", "left_second", "right_first", "right_second"}.issubset(item.record_groups))
            if valid:
                target = next((p.get("details", {}).get("target_side") for p in item.predicates
                               if p.get("predicate") == "concentrated_on_side"), None)
                valid = (target in {"left", "right"} and item.numeric_units["left_change"] == item.numeric_units["right_change"] == METRIC_CATALOG[metric].unit
                         and all(item.sample_counts[group] >= 3 for group in ("left_first", "left_second", "right_first", "right_second")))
                if valid:
                    target_change = abs(item.numeric_values[target + "_change"])
                    other_change = abs(item.numeric_values[("right" if target == "left" else "left") + "_change"])
                    valid = target_change > METRIC_CATALOG[metric].numeric_tolerance and target_change >= 2 * other_change
        elif method in {"verify_temporal_change", "verify_cross_metric_cochange", "compare_session_records"}:
            prefix = "" if method == "verify_temporal_change" else metric + "_"
            before = prefix + ("previous_mean" if method == "compare_session_records" else "first_mean")
            after = prefix + ("current_mean" if method == "compare_session_records" else "second_mean")
            delta = prefix + "difference"
            allowed = {"comparison_supported"} if method == "compare_session_records" else {"increase", "decrease", "co_change", "persistent", "transient"}
            valid = (claim.finding_type in {"temporal_change", "verified_change", "unknown"}
                     and bool(predicates.intersection(allowed))
                     and all(key in item.numeric_values and key in item.numeric_units for key in (before, after, delta)))
            if valid:
                groups = ("previous", "current") if method == "compare_session_records" else ("first_half", "second_half")
                minimum = 1 if method == "compare_session_records" else 3
                valid = (item.numeric_units[before] == item.numeric_units[after] == item.numeric_units[delta] == METRIC_CATALOG[metric].unit
                         and math.isclose(item.numeric_values[after] - item.numeric_values[before], item.numeric_values[delta], abs_tol=1e-12)
                         and abs(item.numeric_values[delta]) > METRIC_CATALOG[metric].numeric_tolerance
                         and all(group in item.record_groups and item.sample_counts[group] >= minimum for group in groups))
                if method == "verify_temporal_change":
                    valid = valid and ((item.numeric_values[delta] > 0 and "increase" in predicates)
                                       or (item.numeric_values[delta] < 0 and "decrease" in predicates))
        elif method == "summarize_records":
            valid = (claim.finding_type in {"descriptive", "conditions_review"}
                     and "comparison_supported" in predicates
                     and f"{metric}_mean" in item.numeric_values
                     and item.numeric_units.get(f"{metric}_mean") == METRIC_CATALOG[metric].unit)
        else:
            valid = False
        if valid:
            accepted.append(item)
    return tuple(accepted)


def evidence_action_match(context, claim, metric, action_id, evidence):
    if action_id not in action_candidates(context, claim) or metric not in claim.metric_codes:
        return None
    spec = ACTION_SPECS[action_id]
    # Measurement agreement, method mentions and paper-wide metric tags establish
    # relevance only. They never authorize a follow-up action.
    if spec["basis"] != "literature" or not verified_finding_evidence(context, claim, metric):
        return None
    domain = {"Jump Test": "jump", "Treadmill Gait Test": "walk", "Treadmill Running Test": "run",
              "Sprint and Gait Test": "walk", "Overground Running Test": "run"}.get(context.test_type)
    if (evidence.domain != domain or not evidence.recommendation_allowed
            or not set(literature_metrics(metric)).intersection(evidence.metric_codes)
            or context.population not in evidence.populations
            or evidence.metadata.get("protocol") not in PROTOCOLS.get(context.test_type, ())):
        return None
    for support in evidence.metadata.get("reviewed_action_support", ()):
        if (support.get("review_status") != "approved" or support.get("action_id") != action_id
                or metric not in support.get("metric_codes", ())
                or support.get("relation") != "direct_action_support"
                or not support.get("quote") or support["quote"] not in evidence.excerpt
                or support.get("content_digest") != evidence.content_digest):
            continue
        return {"evidence_id": evidence.evidence_id, "metric_code": metric, "action_id": action_id,
                "excerpt": support["quote"], "support": ["direct_action_support"],
                "protocol": evidence.metadata["protocol"], "applicability": "reviewed_direct_action_support",
                "reason": support.get("reason", "引用片段已明确审核为该行动的直接支持。")}
    return None


def finding_summary(context, claim, metric):
    """Use only validated numeric fields, with their original units and grouping."""
    if claim.data_origin != "validated_report" or claim.finding_type == "measurement_limitation":
        return ""
    parts = []
    for item in verified_finding_evidence(context, claim, metric):
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
    limitations = tuple(dict.fromkeys(value for item in verified_finding_evidence(context, claim, metric)
                                      for value in concrete_limitations(claim) if value in item.limitations))
    parts = [(value.partition(":")[0], value.partition(":")[2]) if ":" in value else ("", value)
             for value in limitations]
    limitation = "、".join({"left":"左侧", "right":"右侧", "":""}[side] + _LIMIT_LABELS[code]
                           for side, code in parts)
    impact = "".join(dict.fromkeys(_LIMIT_IMPACTS[code] for _, code in parts))
    text = ACTION_SPECS[action_id]["text"].format(metric=label, limitation=limitation, impact=impact)
    conditions = ""
    if action_id in {"track_change", "track_side_changes", "check_repeatability", "check_conditions"}:
        speed = context.test_conditions.get("treadmill_speed")
        if isinstance(speed, (int, float)) and not isinstance(speed, bool):
            conditions = f"本次跑带速度设置为 {speed:.12g} km/h。"
    return finding_summary(context, claim, metric) + conditions + text
