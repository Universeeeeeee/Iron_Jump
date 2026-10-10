"""Fixed result snapshots used to freeze the pre-extraction Excel contract."""
from dataclasses import replace

from config.test_report import JumpQualityNoticeRecord
from config.treadmill_report import GaitCycleRecord, GaitEventRecord, TreadmillRunningReport, summarize
from tests.reporting_fixtures import make_jump_report, make_treadmill_report
from tests.test_overground_walking import processor as walking_processor, walk, CONTACTS
from tests.test_overground_running import processor as running_processor, run, TRAJECTORY


def export_reports():
    snapshot = {"data_source": "simulation", "simulation_description": "固定导出验收数据",
                "beam_quality": {"degraded": True, "masked": [1, 9], "missing": None, "ratio": 0.0}}
    raw = (bytes([1, 0, 0, 0, 0, 0, 0, 1] + [0] * 759 + [1]),)
    common = dict(export_frames=raw, export_timestamps=(0.125,), report_config_snapshot=snapshot)
    jump = replace(make_jump_report([0.0, .25], included=[True, False]), **common,
                   quality_notices=(JumpQualityNoticeRecord("synthetic", .5, 2, .02),))
    cycle_fields = dict(index=0, side="unknown", start_time_s=0., end_time_s=1., gait_cycle_s=1.,
                        stance_phase_s=.6, stance_phase_percent=60., swing_phase_s=.4, swing_phase_percent=40.,
                        step_time_s=.5, single_support_s=.4, single_support_percent=40.,
                        total_double_support_s=0., total_double_support_percent=0.,
                        load_response_s=None, load_response_percent=None, pre_swing_s=None,
                        pre_swing_percent=None, total_flight_time_s=0., stride_length_cm=120.)
    gait = replace(make_treadmill_report([.6], [.7]), **common,
                   gait_cycles=(GaitCycleRecord(**cycle_fields),),
                   raw_gait_events=(GaitEventRecord(0, 0., "unknown", "touch"),),
                   cycle_metric_summaries={"gait_cycle_s": summarize((1.,))},
                   cycle_side_summaries={"left": {"gait_cycle_s": summarize(())}},
                   cycle_asymmetry_percent={"gait_cycle_s": None})
    gait = replace(gait, per_step_results=(gait.per_step_results[0], replace(
        gait.per_step_results[1], is_included_in_statistics=False, contact_time_s=None,
        statistics_exclusion_reason="Missing same-side lift event", quality_flags=("gap_below_minimum",))))
    running_fields = {name: getattr(gait, name) for name, field in gait.__dataclass_fields__.items() if field.init}
    running = TreadmillRunningReport(**running_fields)
    wp = walking_processor(8, stop_type="Software command")
    walk(wp, CONTACTS, 2400)
    walking = wp.build_report("manual", raw, (.125,))
    # This fixture represents saved v1.3 reports, independently of the current
    # processor version. The export must preserve their original metadata.
    walking_snapshot = dict(walking.report_config_snapshot)
    walking_snapshot['algorithm'] = 'overground_walking_v1.3'
    walking_snapshot.pop('fragment_association', None)
    walking_snapshot.pop('narrow_candidate_policy', None)
    walking_snapshot.pop('metric_policy', None)
    walking_snapshot.pop('candidate_exclusion_policy', None)
    walking_snapshot.pop('immature_coalescence_policy', None)
    walking_summary = dict(walking.walking_summary)
    for key in ('record_count', 'confirmed_contacts', 'valid_touches', 'valid_step_times',
                'valid_step_lengths', 'valid_cycle_times', 'valid_stride_lengths',
                'valid_support_cycles', 'valid_contact_durations', 'candidate_decisions'):
        walking_summary.pop(key, None)
    walking_summary['contacts'] = [
        {key: value for key, value in c.items() if key not in {
            'touch_known', 'position_known', 'candidate_outcome', 'touch_sample', 'lift_sample', 'confirmed_sample'}}
        for c in walking_summary['contacts']]
    walking = replace(walking, walking_summary=walking_summary,
                      report_config_snapshot={**walking_snapshot, **snapshot})
    rp = running_processor(8, starting_foot="Left")
    run(rp, TRAJECTORY)
    ground_running = rp.build_report("manual", raw, (.125,))
    running_snapshot = dict(ground_running.report_config_snapshot)
    running_snapshot['algorithm'] = 'overground_running_v1.3'
    running_snapshot['tracking'] = dict(running_snapshot['tracking'])
    running_snapshot['tracking'].pop('fragment_association', None)
    running_snapshot['tracking'].pop('narrow_candidate_width_m', None)
    running_snapshot['tracking'].pop('narrow_candidate_scope', None)
    # Freeze the saved v1.3 running schema; current candidate diagnostics are
    # separately covered by the current-report roundtrip tests.
    running_summary = dict(ground_running.running_summary)
    for key in ('candidate_decisions', 'record_count', 'confirmed_contacts', 'valid_touches',
                'valid_contact_durations', 'valid_step_lengths', 'valid_step_speeds',
                'valid_stride_lengths', 'valid_support_cycles'):
        running_summary.pop(key, None)
    running_summary['contacts'] = [{k: v for k, v in row.items() if k not in {
        'candidate_outcome', 'first_seen_sample', 'touch_sample', 'lift_sample', 'confirmed_sample'}}
        for row in running_summary['contacts']]
    ground_running = replace(ground_running, running_summary=running_summary,
                             report_config_snapshot={**running_snapshot, **snapshot})
    legacy_jump = replace(jump, jump_results=(), export_frames=(), export_timestamps=(), report_config_snapshot={})
    return {"jump": jump, "treadmill_gait": gait, "treadmill_running": running,
            "walking": walking, "overground_running": ground_running, "legacy_jump": legacy_jump}


def workbook_cells(book):
    return [{"name": sheet.title, "rows": [[{"value": cell.value, "type": cell.data_type,
              "number_format": cell.number_format} for cell in row] for row in sheet.iter_rows()]}
            for sheet in book.worksheets]
