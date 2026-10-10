"""Canonical metric identities and units used by report evidence models."""

from __future__ import annotations

from .models import MetricDefinition


_METRICS = (
    MetricDefinition(metric_code="touch_count", unit="count", label="触地次数", record_types=("report",), numeric_tolerance=0),
    MetricDefinition(metric_code="lift_count", unit="count", label="离地次数", record_types=("report",), numeric_tolerance=0),
    MetricDefinition(metric_code="jump_count", unit="count", label="有效跳跃次数", record_types=("report",), numeric_tolerance=0),
    MetricDefinition(metric_code="air_time_s", unit="s", label="腾空时间", record_types=("jump",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="jump_height_m", unit="m", label="跳跃高度", record_types=("jump",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="contact_time_s", unit="s", label="触地时间", record_types=("jump", "step"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="cycle_time_s", unit="s", label="跳跃周期", record_types=("jump",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="cadence_jumps_per_min", unit="jumps/min", label="跳跃频率", record_types=("jump",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="flight_time_s", unit="s", label="腾空时间", record_types=("step",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="step_time_s", unit="s", label="步时", record_types=("step", "gait_cycle"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="gait_cycle_s", unit="s", label="步态周期", record_types=("step", "gait_cycle"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="step_length_cm", unit="cm", label="步长", record_types=("step",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="stride_length_cm", unit="cm", label="步幅", record_types=("step", "gait_cycle"), numeric_tolerance=0.1),
    MetricDefinition(metric_code="speed_m_s", unit="m/s", label="速度", record_types=("step",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="cadence_steps_per_s", unit="steps/s", label="步频", record_types=("step",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="cadence_steps_per_min", unit="steps/min", label="步频", record_types=("step",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="double_support_s", unit="s", label="双支撑时间", record_types=("step",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="single_support_s", unit="s", label="单支撑时间", record_types=("step", "gait_cycle"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="stance_phase_s", unit="s", label="支撑相", record_types=("step", "gait_cycle"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="stance_phase_percent", unit="%", label="支撑相占比", record_types=("gait_cycle",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="swing_phase_s", unit="s", label="摆动相", record_types=("step", "gait_cycle"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="swing_phase_percent", unit="%", label="摆动相占比", record_types=("gait_cycle",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="total_double_support_s", unit="s", label="总双支撑时间", record_types=("gait_cycle",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="total_double_support_percent", unit="%", label="总双支撑占比", record_types=("gait_cycle",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="load_response_s", unit="s", label="负重反应期", record_types=("step", "gait_cycle"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="load_response_percent", unit="%", label="负重反应期占比", record_types=("gait_cycle",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="pre_swing_s", unit="s", label="预摆动期", record_types=("step", "gait_cycle"), numeric_tolerance=0.001),
    MetricDefinition(metric_code="pre_swing_percent", unit="%", label="预摆动期占比", record_types=("gait_cycle",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="total_flight_time_s", unit="s", label="总腾空时间", record_types=("gait_cycle",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="imbalance_percent", unit="%", label="不平衡率", record_types=("step",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="gap_between_feet_cm", unit="cm", label="双足间距", record_types=("step",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="step_length_m", unit="m", label="地面步长", record_types=("ground_step",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="stride_length_m", unit="m", label="地面步幅", record_types=("ground_cycle",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="duration_s", unit="s", label="单次通过时长", record_types=("report",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="passage_speed_m_s", unit="m/s", label="落点推进距离与通过时长之比", record_types=("report",), numeric_tolerance=0.01),
)

METRIC_CATALOG = {metric.metric_code: metric for metric in _METRICS}


def metric_definition(metric_code: str) -> MetricDefinition:
    try:
        return METRIC_CATALOG[metric_code]
    except KeyError as exc:
        raise KeyError(f"Unknown metric code: {metric_code}") from exc


def metrics_for_record_type(record_type: str) -> tuple[MetricDefinition, ...]:
    return tuple(
        metric for metric in _METRICS if record_type in metric.record_types
    )
