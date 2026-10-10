"""Build Excel workbooks from saved report snapshots, without Qt or an engine."""
from __future__ import annotations

from openpyxl import Workbook

from config.test_report import TestReport, JumpTestReport, GaitTestReport
from config.overground_running_report import OvergroundRunningReport
from config.treadmill_report import TreadmillGaitReport, TreadmillRunningReport


def has_export_data(report: TestReport) -> bool:
    frames = report.export_frames
    has_jump_metrics = isinstance(report, JumpTestReport) and any(
        (
            report.air_times,
            report.contact_times,
            report.cycle_times,
            report.jump_heights,
            report.cadences,
        )
    )

    has_treadmill_steps = isinstance(
        report, (TreadmillGaitReport, TreadmillRunningReport)
    ) and bool(
        report.per_step_results
        or report.gait_cycles
        or report.raw_gait_events
    )

    has_walking = isinstance(report, GaitTestReport) and bool(report.walking_summary)
    has_running = isinstance(report, OvergroundRunningReport)
    return bool(frames or has_jump_metrics or has_treadmill_steps or has_walking or has_running)


def build_report_workbook(report: TestReport) -> Workbook:
    """Preserve the existing worksheet order, values, and missing-value conventions."""
    frames = report.export_frames
    timestamps = report.export_timestamps
    has_walking = isinstance(report, GaitTestReport) and bool(report.walking_summary)
    has_running = isinstance(report, OvergroundRunningReport)
    wb = Workbook()
    snapshot = getattr(report, "report_config_snapshot", {})
    import json
    quality_sheet = wb.create_sheet("设备质量")
    quality = snapshot.get("beam_quality")
    if quality is None:
        quality_sheet.append(["状态", "未记录（不代表无异常）"])
    else:
        def append_quality(path, value):
            if isinstance(value, dict):
                for key, item in value.items():
                    append_quality(f"{path}.{key}" if path else key, item)
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    append_quality(f"{path}[{index}]", item)
            else:
                quality_sheet.append([path, value])
        append_quality("", quality)
    if snapshot.get("data_source") == "simulation":
        provenance = wb.create_sheet("数据来源")
        provenance.append(["数据来源", "模拟演示数据，非受试者实测"])
        provenance.append(["说明", snapshot.get("simulation_description", "")])
    default_ws = wb.active
    if frames:
        default_ws.title = "LED Frames"
        default_ws.append(["timestamp", "hex_string"])
        for ts, bits in zip(timestamps, frames):
            hex_bytes = []
            for i in range(0, len(bits), 8):
                byte_val = 0
                for j in range(8):
                    if i + j < len(bits):
                        byte_val |= (bits[i + j] << j)
                hex_bytes.append(byte_val)
            hex_str = " ".join(f"{b:02x}" for b in hex_bytes)
            default_ws.append([ts, hex_str])
    else:
        wb.remove(default_ws)

    if has_running:
        from reporting.overground_running import export_sheets
        export_sheets(wb, report)

    if has_walking:
        import json
        summary = report.walking_summary
        ws_summary = wb.create_sheet("Walking Summary")
        ws_summary.append(["metric", "value"])
        for key, value in summary.items():
            if not isinstance(value, (list, dict)):
                ws_summary.append([key, value])
        ws_device = wb.create_sheet("Device and Config")
        for key, value in snapshot.items():
            ws_device.append([key, json.dumps(value, ensure_ascii=False)])
        for key in ("contacts", "steps", "cycles", "stops", "issues") + (
                ("candidate_decisions",) if "candidate_decisions" in summary else ()):
            records = summary[key]
            ws = wb.create_sheet("Walking " + key)
            if records:
                columns = (list(dict.fromkeys(column for record in records for column in record))
                           if key == 'candidate_decisions' else list(records[0]))
                ws.append(columns)
                for record in records:
                    ws.append([json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                               for value in (record.get(column) for column in columns)])

    if isinstance(report, JumpTestReport):
        ws = wb.create_sheet("Jump Metrics")
        ws.append(
            [
                "index",
                "air_time_s",
                "contact_time_s",
                "cycle_time_s",
                "jump_height_m",
                "cadence_jumps_per_min",
                "lift_time_s",
                "touch_time_s",
                "is_included_in_statistics",
                "statistics_exclusion_reason",
                "quality_flags",
            ]
        )
        for row in _jump_metric_rows(report):
            ws.append(row)
        if report.quality_notices:
            notice_ws = wb.create_sheet("Jump Quality Notices")
            notice_ws.append(
                ["kind", "time_s", "cluster_length", "ratio"]
            )
            for notice in report.quality_notices:
                notice_ws.append(
                    [
                        notice.kind,
                        notice.time_s,
                        notice.cluster_length,
                        notice.ratio,
                    ]
                )

    if isinstance(report, (TreadmillGaitReport, TreadmillRunningReport)):
        # Sheet 2: Treadmill Steps
        ws_steps = wb.create_sheet("Treadmill Steps")
        ws_steps.append(TREADMILL_EXPORT_COLUMNS)
        for row in _treadmill_metric_rows(report):
            ws_steps.append(row)

        if report.gait_cycles:
            ws_cycles = wb.create_sheet("步态周期")
            ws_cycles.append(GAIT_CYCLE_EXPORT_HEADERS)
            for row in _gait_cycle_rows(report):
                ws_cycles.append(row)

        if report.raw_gait_events:
            ws_events = wb.create_sheet("原始步态事件")
            ws_events.append(["序号", "时间(s)", "脚", "事件"])
            for event in report.raw_gait_events:
                ws_events.append([
                    event.index + 1,
                    event.time_s,
                    _side_label(event.side),
                    "触地" if event.kind == "touch" else "离地",
                ])

        if report.cycle_metric_summaries:
            ws_cycle_summary = wb.create_sheet("步态周期统计")
            ws_cycle_summary.append([
                "指标", "总体数量", "总体均值",
                "左脚数量", "左脚均值", "右脚数量", "右脚均值",
                "不对称率(%)",
            ])
            for name, summary in report.cycle_metric_summaries.items():
                left = report.cycle_side_summaries.get("left", {}).get(name)
                right = report.cycle_side_summaries.get("right", {}).get(name)
                ws_cycle_summary.append([
                    GAIT_CYCLE_METRIC_LABELS.get(name, name),
                    summary.count, _excel_cycle_value(summary.mean),
                    left.count if left else 0,
                    _excel_cycle_value(left.mean if left else None),
                    right.count if right else 0,
                    _excel_cycle_value(right.mean if right else None),
                    _excel_cycle_value(
                        report.cycle_asymmetry_percent.get(name)
                    ),
                ])

        # Sheet 3 (optional): Metric Summaries
        metric_summaries = report.metric_summaries
        if metric_summaries:
            ws_metrics = wb.create_sheet("Metric Summaries")
            ws_metrics.append(["metric", "count", "mean", "min", "max", "std", "cv_percent"])
            for name, sm in metric_summaries.items():
                ws_metrics.append([
                    name, sm.count,
                    _fmt(sm.mean), _fmt(sm.min), _fmt(sm.max),
                    _fmt(sm.std), _fmt(sm.cv_percent),
                ])

    return wb


TREADMILL_EXPORT_COLUMNS = [
    "index",
    "side",
    "row_status",
    "is_event_valid",
    "is_included_in_statistics",
    "contact_time_s",
    "flight_time_s",
    "step_time_s",
    "step_length_cm",
    "gap_between_feet_cm",
    "distance_cm",
    "speed_m_s",
    "correction_source",
    "statistics_exclusion_reason",
    "quality_flags",
    "step_reference_cm",
]

GAIT_CYCLE_EXPORT_FIELDS = [
    "index", "side", "start_time_s", "end_time_s", "gait_cycle_s",
    "stride_length_cm", "stance_phase_s", "stance_phase_percent",
    "swing_phase_s",
    "swing_phase_percent", "step_time_s", "single_support_s",
    "single_support_percent", "total_double_support_s",
    "total_double_support_percent", "load_response_s",
    "load_response_percent", "pre_swing_s", "pre_swing_percent",
    "total_flight_time_s", "is_included_in_statistics",
    "statistics_exclusion_reason", "quality_flags",
]

GAIT_CYCLE_EXPORT_HEADERS = [
    "序号", "脚", "开始时间(s)", "结束时间(s)", "步态周期(s)",
    "步幅(cm)", "支撑相(s)", "支撑相(%)", "摆动相(s)", "摆动相(%)",
    "步时间(s)", "单支撑(s)", "单支撑(%)", "总双支撑(s)",
    "总双支撑(%)", "负荷反应期(s)", "负荷反应期(%)",
    "摆动前期(s)", "摆动前期(%)", "腾空时间(s)", "纳入统计",
    "未纳入原因", "质量提示",
]

GAIT_CYCLE_METRIC_LABELS = {
    "gait_cycle_s": "步态周期 (s)",
    "stride_length_cm": "步幅 (cm)",
    "stance_phase_s": "支撑相 (s)",
    "stance_phase_percent": "支撑相 (%)",
    "swing_phase_s": "摆动相 (s)",
    "swing_phase_percent": "摆动相 (%)",
    "step_time_s": "步时间 (s)",
    "single_support_s": "单支撑 (s)",
    "single_support_percent": "单支撑 (%)",
    "total_double_support_s": "总双支撑 (s)",
    "total_double_support_percent": "总双支撑 (%)",
    "load_response_s": "负荷反应期 (s)",
    "load_response_percent": "负荷反应期 (%)",
    "pre_swing_s": "摆动前期 (s)",
    "pre_swing_percent": "摆动前期 (%)",
    "total_flight_time_s": "腾空时间 (s)",
}

def _jump_metric_rows(report: JumpTestReport) -> list[list[object]]:
    if report.jump_results:
        return [
            [
                record.index,
                _optional_excel_value(record.air_time_s),
                _optional_excel_value(record.contact_time_s),
                _optional_excel_value(record.cycle_time_s),
                _optional_excel_value(record.jump_height_m),
                _optional_excel_value(record.cadence_jumps_per_min),
                _optional_excel_value(record.lift_time_s),
                _optional_excel_value(record.touch_time_s),
                record.is_included_in_statistics,
                record.statistics_exclusion_reason or "",
                ",".join(record.quality_flags),
            ]
            for record in report.jump_results
        ]

    max_len = max(
        len(report.air_times),
        len(report.jump_heights),
        len(report.contact_times) + (1 if report.contact_times else 0),
        len(report.cycle_times) + (1 if report.cycle_times else 0),
        len(report.cadences) + (1 if report.cadences else 0),
        0,
    )
    rows = []
    for index in range(max_len):
        prior_index = index - 1
        rows.append(
            [
                index + 1,
                _value_at(report.air_times, index),
                _value_at(report.contact_times, prior_index),
                _value_at(report.cycle_times, prior_index),
                _value_at(report.jump_heights, index),
                _value_at(report.cadences, prior_index),
                "",
                "",
                True,
                "",
                "",
            ]
        )
    return rows

def _value_at(values: tuple, index: int):
    return values[index] if 0 <= index < len(values) else ""

def _optional_excel_value(value):
    return value if value is not None else ""

def _fmt(value: float | None) -> str:
    """Format an optional float value for table display."""
    if value is None:
        return ""
    return f"{value:.3f}"

def _side_label(side: str) -> str:
    return {"left": "左脚", "right": "右脚", "unknown": "未知"}.get(side, side)

def _excel_cycle_value(value):
    return "N/A" if value is None else value

_STATISTICS_REASON_LABELS = {
    "Touch was replaced before lift": "重复触地前未检测到正常离地",
    "Missing same-side lift event": "缺少同侧离地事件",
    "Contact time below minimum threshold": "触地时间低于最小阈值",
    "Flight time outside acceptable range": "腾空时间不在允许范围",
    "Step length below minimum threshold": "步长低于最小阈值",
    "Excluded by automatic_data_filter": "被自动数据过滤排除",
}

_QUALITY_FLAG_LABELS = {
    "gap_below_minimum": "两脚间距低于最小阈值",
    "running_overlap_above_tolerance": "跑步时双脚重叠超过容差",
    "non_positive_stride_length": "步幅计算结果非正值",
}

def _statistics_reason_label(reason: str | None) -> str:
    if reason is None:
        return "原因未知"
    return _STATISTICS_REASON_LABELS.get(reason, reason)

def _quality_flags_text(quality_flags: tuple[str, ...]) -> str:
    return "、".join(
        _QUALITY_FLAG_LABELS.get(flag, flag)
        for flag in quality_flags
    )

def _treadmill_metric_rows(report: TreadmillGaitReport | TreadmillRunningReport) -> list[list[object]]:
    """Extract key columns from per_step_results for Excel export and testing."""
    rows = []
    for step in report.per_step_results:
        rows.append(
            [
                step.index,
                step.side,
                step.row_status,
                step.is_event_valid,
                step.is_included_in_statistics,
                _excel_cycle_value(step.contact_time_s),
                _excel_cycle_value(step.flight_time_s),
                _excel_cycle_value(step.step_time_s),
                _excel_cycle_value(step.step_length_cm),
                _excel_cycle_value(step.gap_between_feet_cm),
                _excel_cycle_value(step.distance_cm),
                _excel_cycle_value(step.speed_m_s),
                step.correction_source,
                (
                    _statistics_reason_label(step.statistics_exclusion_reason)
                    if step.statistics_exclusion_reason is not None
                    else "N/A"
                ),
                _quality_flags_text(step.quality_flags) or "N/A",
                _excel_cycle_value(step.step_reference_cm),
            ]
        )
    return rows

def _gait_cycle_rows(report: TreadmillGaitReport | TreadmillRunningReport) -> list[list[object]]:
    rows = []
    for cycle in report.gait_cycles:
        row = [
            _excel_cycle_value(getattr(cycle, name))
            for name in GAIT_CYCLE_EXPORT_FIELDS
        ]
        row[0] = cycle.index + 1
        row[1] = _side_label(cycle.side)
        included_index = GAIT_CYCLE_EXPORT_FIELDS.index(
            "is_included_in_statistics"
        )
        exclusion_reason_index = GAIT_CYCLE_EXPORT_FIELDS.index(
            "statistics_exclusion_reason"
        )
        quality_flags_index = GAIT_CYCLE_EXPORT_FIELDS.index("quality_flags")
        row[included_index] = (
            "是" if cycle.is_included_in_statistics else "否"
        )
        if cycle.statistics_exclusion_reason is not None:
            row[exclusion_reason_index] = _statistics_reason_label(
                cycle.statistics_exclusion_reason
            )
        row[quality_flags_index] = (
            _quality_flags_text(cycle.quality_flags) or "N/A"
        )
        rows.append(row)
    return rows
