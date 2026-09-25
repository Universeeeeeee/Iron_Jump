"""Deterministic gait questions with explicit sample scope and evidence links."""

from dataclasses import dataclass
import math

from config.treadmill_report import TreadmillGaitReport, summarize


@dataclass(frozen=True)
class GaitAnswer:
    topic: str
    text: str
    references: tuple[tuple[str, int], ...] = ()


METRICS = (
    ("step", "cadence_steps_per_s", "步频", "步/分钟", 60.0),
    ("step", "contact_time_s", "触地时间", "秒", 1.0),
    ("cycle", "gait_cycle_s", "步态周期", "秒", 1.0),
    ("cycle", "stance_phase_percent", "支撑期占比", "%", 1.0),
    ("cycle", "swing_phase_percent", "摆动期占比", "%", 1.0),
)


def _records(report, kind):
    return report.per_step_results if kind == "step" else report.gait_cycles


def _bounds(record, kind):
    if kind == "cycle":
        return record.start_time_s, record.end_time_s
    end = record.time_s
    if end is None:
        return None, None
    return end - (record.contact_time_s or 0), end


def _eligible(record, kind, metric, boundaries):
    value = getattr(record, metric)
    start, end = _bounds(record, kind)
    return (
        record.is_included_in_statistics
        and (kind == "cycle" or record.is_event_valid)
        and value is not None and math.isfinite(value)
        and start is not None and end is not None
        and not any(start < point < end for point in boundaries)
    )


def _mean(records, metric, scale):
    return summarize(tuple(getattr(r, metric) * scale for r in records)).mean


def _asymmetry(left, right):
    denominator = (left + right) / 2
    return abs(left - right) / denominator * 100 if denominator > 0 else None


def answer_gait_question(report, question: str, previous_topic: str = "") -> GaitAnswer:
    """Answer supported report questions without model inference or network IO."""
    if not isinstance(report, TreadmillGaitReport):
        return GaitAnswer("", "请打开一份跑步机步态报告后再询问步态专项分析。")
    if any(word in question for word in ("没算", "排除", "无效", "质量")):
        topic = "quality"
    elif any(word in question for word in ("前后", "后半", "前半", "变化", "哪里")):
        topic = "change"
    elif any(word in question for word in ("左右", "左脚", "右脚", "对称", "差异")):
        topic = "symmetry"
    elif any(word in question for word in ("稳定", "步频", "周期")):
        topic = "stability"
    elif any(word in question for word in ("具体", "证据", "详细", "为什么", "哪些")) and previous_topic:
        topic = previous_topic
    else:
        return GaitAnswer("", "可以问：左右脚差异怎么样、步频稳定吗、前后半程有什么变化、哪些数据没算进去。")

    refs = []
    lines = []
    relative_changes = []
    boundaries = report.report_config_snapshot.get("pause_boundaries_s", ())
    if topic == "quality":
        for kind, label in (("step", "逐步记录"), ("cycle", "完整周期")):
            records = _records(report, kind)
            excluded = [r for r in records if not r.is_included_in_statistics
                        or (kind == "step" and not r.is_event_valid)]
            lines.append(f"{label}共 {len(records)} 条，排除 {len(excluded)} 条。")
            for record in excluded:
                reason = record.statistics_exclusion_reason or getattr(record, "event_invalid_reason", None) or "未纳入统计"
                lines.append(f"{label} {record.index + 1}：{reason}。")
                refs.append((kind, record.index))
        lines.append(f"另有 {len(report.boundary_partials)} 个未闭合边界片段，不作为完整周期统计。")
        for kind, metric, label, _unit, _scale in METRICS:
            missing = [r for r in _records(report, kind)
                       if r.is_included_in_statistics
                       and (getattr(r, metric) is None or not math.isfinite(getattr(r, metric)))]
            if missing:
                numbers = "、".join(str(r.index + 1) for r in missing)
                lines.append(f"{label}另有 {len(missing)} 条缺失或非有限值：{'逐步' if kind == 'step' else '周期'} {numbers}。")
                refs.extend((kind, r.index) for r in missing)
        lines.append("每项指标还会单独排除缺失、非有限数值和跨暂停记录；真实零值保留。")
    else:
        all_bounds = [_bounds(r, "cycle") for r in report.gait_cycles]
        if not all_bounds and topic == "change":
            return GaitAnswer(topic, "完整步态周期不足，暂不能进行专项比较。")
        if topic == "change":
            midpoint = (min(a for a, _ in all_bounds) + max(b for _, b in all_bounds)) / 2
            lines.append(f"按完整周期覆盖范围中点 {midpoint:.3f} 秒分段，跨中点的记录不参与前后比较；暂停时长不计入采集时间。")
        for kind, metric, label, unit, scale in METRICS:
            if topic == "symmetry" and kind == "step":
                continue
            if topic == "stability" and metric not in {"cadence_steps_per_s", "gait_cycle_s"}:
                continue
            records = [r for r in _records(report, kind) if _eligible(r, kind, metric, boundaries)]
            if topic == "stability":
                refs.extend((kind, r.index) for r in records)
                summary = summarize(tuple(getattr(r, metric) * scale for r in records))
                if summary.count < 3:
                    lines.append(f"{label}有效样本 {summary.count} 条，不足 3 条，不能评价波动。")
                else:
                    cv = f"{summary.cv_percent:.2f}%" if summary.cv_percent is not None else "无法计算（均值为零）"
                    lines.append(f"{label}：均值 {summary.mean:.3f} {unit}，总体标准差 {summary.std:.3f} {unit}，CV {cv}，有效样本 {summary.count} 条。")
                continue
            if topic == "symmetry":
                first = [r for r in records if r.side == "left"]
                second = [r for r in records if r.side == "right"]
                names = ("左", "右")
            else:
                first = [r for r in records if _bounds(r, kind)[1] <= midpoint]
                second = [r for r in records if _bounds(r, kind)[0] >= midpoint]
                names = ("前半", "后半")
            refs.extend((kind, r.index) for r in (*first, *second))
            if min(len(first), len(second)) < 3:
                lines.append(f"{label}：{names[0]} {len(first)} 条、{names[1]} {len(second)} 条；每组至少需 3 条，样本不足。")
                continue
            a, b = _mean(first, metric, scale), _mean(second, metric, scale)
            text = f"{label}：{names[0]} {a:.3f} {unit}（{len(first)} 条），{names[1]} {b:.3f} {unit}（{len(second)} 条）。"
            if topic == "symmetry":
                asymmetry = _asymmetry(a, b)
                text += f"不对称率 {asymmetry:.2f}%。" if asymmetry is not None else "均值分母为零，不计算不对称率。"
            else:
                difference_unit = "个百分点" if unit == "%" else unit
                text += f"后减前 {b - a:+.3f} {difference_unit}。"
                if a != 0:
                    relative_changes.append((abs((b - a) / a * 100), label))
            lines.append(text)
            if topic == "change" and kind == "cycle":
                side_means = []
                side_counts = []
                for group in (first, second):
                    left = [r for r in group if r.side == "left"]
                    right = [r for r in group if r.side == "right"]
                    side_counts.append((len(left), len(right)))
                    side_means.append(
                        _asymmetry(_mean(left, metric, scale), _mean(right, metric, scale))
                        if min(len(left), len(right)) >= 3 else None
                    )
                if all(value is not None for value in side_means):
                    lines.append(f"{label}不对称率：前半 {side_means[0]:.2f}%，后半 {side_means[1]:.2f}%，变化 {side_means[1] - side_means[0]:+.2f} 个百分点；有效周期数前半左/右 {side_counts[0][0]}/{side_counts[0][1]}，后半左/右 {side_counts[1][0]}/{side_counts[1][1]}。")
                else:
                    lines.append(f"{label}的分段不对称率条件不足（各半段各侧需 3 个有效周期且均值分母非零）。")
        if topic == "change" and relative_changes:
            largest, label = max(relative_changes)
            if largest < 0.005:
                lines.append("本页可比较指标的相对均值变化均小于 0.005%，不区分最大变化项。")
            else:
                lines.append(f"本页可比较指标中，{label}的相对均值变化幅度最大：{largest:.2f}%（以前半均值为基准，零基准不参与排名；相同幅度可能并列）。")
        lines.append("证据仅限本次测试；CV 和差值是描述性统计，不据此判断正常、疲劳、疾病或变化原因。")
    if boundaries:
        lines.append(f"本次含 {len(boundaries)} 次暂停；跨暂停配对已排除。")
    if report.report_config_snapshot.get("data_source") == "simulation":
        lines.insert(0, "这是模拟演示数据，非受试者实测。")
    return GaitAnswer(topic, "\n".join(lines), tuple(dict.fromkeys(refs)))
