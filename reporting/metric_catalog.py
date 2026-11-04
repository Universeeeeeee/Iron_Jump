"""Canonical metric identities and units used by report evidence models."""

from __future__ import annotations

from .models import MetricDefinition


_METRICS = (
    MetricDefinition(metric_code="contact_phase_s", unit="s", label="初始接触阶段（光学）", record_types=("ground_contact",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="contact_phase_percent", unit="%", label="初始接触阶段占比", record_types=("ground_contact",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="foot_flat_s", unit="s", label="支撑平台阶段（光学）", record_types=("ground_contact",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="foot_flat_percent", unit="%", label="支撑平台阶段占比", record_types=("ground_contact",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="propulsive_phase_s", unit="s", label="最终退出阶段（光学）", record_types=("ground_contact",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="propulsive_phase_percent", unit="%", label="最终退出阶段占比", record_types=("ground_contact",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="flight_height_m", unit="m", label="腾空估计高度", record_types=("ground_step",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="stride_angle_deg", unit="deg", label="Alpha轨迹角（估计）", record_types=("ground_step",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="duty_factor_percent", unit="%", label="Duty factor（单步分母）", record_types=("ground_contact",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="acceleration_m_s2", unit="m/s²", label="加速度（两步时间口径）", record_types=("ground_step",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="toe_acceleration_m_s2", unit="m/s²", label="脚尖参考加速度", record_types=("ground_step",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="toe_step_length_m", unit="m", label="脚尖步长", record_types=("ground_step",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="toe_stride_length_m", unit="m", label="脚尖跨步长", record_types=("ground_cycle",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="toe_speed_m_s", unit="m/s", label="脚尖参考速度", record_types=("ground_step",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="imbalance_theory_percent", unit="%", label="Imb（理论分母）", record_types=("ground_contact",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="imbalance_sample_percent", unit="%", label="Imb（截图分母）", record_types=("ground_contact",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="step_time_percent", unit="%", label="步时占同侧周期比例", record_types=("ground_step",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="single_support_percent", unit="%", label="本侧单支撑占比", record_types=("ground_cycle",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="cycle_single_support_total_s", unit="s", label="周期内两侧单支撑合计", record_types=("ground_cycle",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="recognized_step_length_m", unit="m", label="落脚点平均步长", record_types=("recognized_footprint",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="recognized_step_time_s", unit="s", label="识别脚印步间时间", record_types=("recognized_footprint",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="recognized_speed_m_s", unit="m/s", label="落脚点平均速度", record_types=("recognized_footprint",), numeric_tolerance=0.01),
    MetricDefinition(metric_code="recognized_cadence_per_min", unit="steps/min", label="识别步频", record_types=("recognized_footprint",), numeric_tolerance=0.1),
    MetricDefinition(metric_code="recognized_contact_time_s", unit="s", label="已识别脚印完整接触时间", record_types=("recognized_footprint",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="recognized_steps", unit="count", label="识别步数", record_types=("report",), numeric_tolerance=0),
    MetricDefinition(metric_code="footfall_time_s", unit="s", label="可靠落脚时间", record_types=("ground_footfall",), numeric_tolerance=0.001),
    MetricDefinition(metric_code="raw_landing_position_m", unit="m", label="发布时原始落脚位置", record_types=("ground_footfall",), numeric_tolerance=0.001),
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
    MetricDefinition(metric_code="centre_m", unit="m", label="地面走路中心位置", record_types=("ground_contact",), numeric_tolerance=0.001),
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
