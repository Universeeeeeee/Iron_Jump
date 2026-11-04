"""Report completion uses this capture's time/position evidence and keeps raw certificates."""
from copy import deepcopy

import pytest

from config.overground_running_report import OvergroundRunningReport
from engine.ground_metric_completion import complete_ground_metrics
from reporting.recognized_gait import recognized_gait
from tests.test_recognized_gait import sample


def incomplete():
    s = sample()
    s.update(duration_s=None, mean_stride_m=None, single_support_s=None,
             double_support_s=None, passage_speed_m_s=None)
    return s


def test_observed_spans_complete_statistics_without_rewriting_certificates():
    source = incomplete()
    before = deepcopy(source)
    result = complete_ground_metrics(source, 'walk')
    assert source == before and result['contacts'] == source['contacts']
    assert result['duration_s'] == pytest.approx(1.3)
    assert result['mean_stride_m'] == pytest.approx(1.)
    assert result['single_support_s'] == pytest.approx(.6)
    assert result['double_support_s'] == 0
    data = recognized_gait(result)
    assert data['mean_contact_s'] == pytest.approx(.3)
    assert data['interval_count'] == 2
    assert complete_ground_metrics(result, 'walk') == result
    data['rows'].clear()
    assert len(recognized_gait(result)['rows']) == 3


def test_missing_release_learns_from_the_same_capture():
    source = incomplete()
    source['contacts'][1]['end'] = None
    result = complete_ground_metrics(source, 'walk')
    data = recognized_gait(result)
    assert data['rows'][1]['contact_s'] == pytest.approx(.3)
    method = next(m for m in result['metric_completion']['methods']
                  if m['contact_id'] == 1 and m['metric'] == 'contact_s')
    assert method['basis'] == 'within_capture_duty_ratio'
    assert method['duty_ratio'] == pytest.approx(.3)


def test_no_release_evidence_does_not_create_contact_or_support_constants():
    source = incomplete()
    for c in source['contacts']:
        c['end'] = None
    result = complete_ground_metrics(source, 'walk')
    assert recognized_gait(result)['mean_contact_s'] is None
    assert result['single_support_s'] is None and result['double_support_s'] is None
    assert result['duration_s'] == 1.
    assert result['mean_stride_m'] == pytest.approx(1.)


def test_unresolved_candidates_do_not_erase_known_landing_intervals():
    source = incomplete()
    source['candidate_decisions'] = [{'source': 'narrow', 'outcome': 'unresolved', 'epoch': 0, 'first_sample': 400}]
    assert recognized_gait(source)['interval_count'] == 1
    result = complete_ground_metrics(source, 'walk')
    assert recognized_gait(result)['interval_count'] == 2
    assert result['candidate_decisions'] == source['candidate_decisions']


@pytest.mark.parametrize('code', ['frame_gap', 'counter_reset', 'turn_detected'])
def test_real_time_breaks_are_not_used_as_step_or_support_evidence(code):
    source = incomplete()
    source['issues'] = [{'time_s': .2, 'code': code}]
    result = complete_ground_metrics(source, 'walk')
    assert recognized_gait(result)['rows'][1]['step_time_s'] is None
    assert not result['metric_completion']['cycles']
    if code == 'counter_reset':
        assert result['duration_s'] is None


def test_long_interval_uses_capture_cadence_instead_of_a_giant_stride():
    source = incomplete()
    # A measured .5 s step plus a 1.5 s span across missing intermediate feet.
    source['event_publications'][2]['touch_sample'] = 2100
    source['contacts'][2].update(start=2., end=2.3, touch_s={'valid': True, 'value': 2.})
    source['contacts'][2]['landing_reference']['value'] = 2.2
    source['candidate_decisions'] = [{'source': 'narrow', 'outcome': 'unresolved', 'epoch': 0, 'first_sample': 1000}]
    result = complete_ground_metrics(source, 'walk')
    row = recognized_gait(result)['rows'][2]
    assert row['interval_steps'] == 3
    assert row['step_time_s'] == pytest.approx(.5)
    assert row['step_length_m'] == pytest.approx(.5)
    assert result['mean_stride_m'] == pytest.approx(1.)
    cycle = result['metric_completion']['cycles'][0]
    assert cycle['duration_s'] == pytest.approx(1.)
    assert cycle['swing_s'] + cycle['contact_s'] == pytest.approx(cycle['duration_s'])
    assert sum(cycle[k] for k in ('flight_s', 'single_support_s', 'double_support_s')) == pytest.approx(cycle['duration_s'])


def test_a_measured_slow_step_is_not_replaced_by_the_majority_cadence():
    source = incomplete()
    source['event_publications'][2]['touch_sample'] = 2100
    source['contacts'][2].update(start=2., end=2.3, touch_s={'valid': True, 'value': 2.})
    row = recognized_gait(complete_ground_metrics(source, 'walk'))['rows'][2]
    assert row['interval_steps'] == 1
    assert row['step_time_s'] == pytest.approx(1.5)


def test_running_report_and_history_share_the_completed_data():
    from data.subject_store import _report_detail, _report_from_detail
    source = incomplete()
    source['groups'] = {'all': {key: {'mean': None, 'count': 0} for key in (
        'duration_s', 'length_m', 'contact_s', 'swing_s', 'flight_s', 'single_support_s', 'double_support_s')}}
    report = OvergroundRunningReport(touch_count=3, running_summary=source)
    restored = _report_from_detail(_report_detail(report))
    assert restored.running_summary == report.running_summary
    assert report.running_summary['groups']['all']['swing_s']['mean'] == pytest.approx(.7)
    assert source['duration_s'] is None


def test_previous_completion_is_upgraded_for_footfall_details_without_losing_raw_data():
    source = incomplete()
    source['footfalls'] = [{'contact_id': i, 'epoch': 0,
                           'contact_s': {'value': None, 'valid': False, 'missing_reason': 'competing_source'},
                           'step_time_s': {'value': None, 'valid': False, 'missing_reason': 'no_valid_step_relationship'}}
                          for i in range(3)]
    source['recognized_measurements'] = recognized_gait(source)
    source['metric_completion'] = {'policy': 'observed_landing_sequence_completion_v1', 'original_aggregates': {}}
    original = deepcopy(source)
    result = complete_ground_metrics(source, 'walk')
    assert source == original and result['contacts'] == original['contacts']
    assert result['footfalls'][1]['step_time_s']['value'] == pytest.approx(.5)
    assert result['footfalls'][1]['contact_s']['value'] == pytest.approx(.3)
    assert result['metric_completion']['source_records']['footfalls']['1']['contact_s'] == original['footfalls'][1]['contact_s']
    assert complete_ground_metrics(result, 'walk') == result
