from copy import deepcopy

import pytest

from engine.ground_derived_metrics import derive_metrics
from engine.ground_bilateral import _statistics
from engine.ground_metric_evidence import metric
from tests.test_ground_bilateral import measured


def test_manual_height_and_alpha_example_use_single_flight():
    s = measured('run').summary()
    s['steps'][0]['flight_s'] = metric(.112)
    s['steps'][0]['length_m'] = metric(.98)
    d = derive_metrics(s, 'run')['steps'][0]['metrics']
    assert d['flight_height_m']['value'] == pytest.approx(.0153768272)
    assert d['stride_angle_deg']['value'] == pytest.approx(3.59131917425)


def test_imbalance_versions_reproduce_theory_and_screenshot_without_row_shift():
    s = measured('run').summary()
    for row, tc in zip(s['contacts'], [.079, .131, .119]):
        row['contact_s'] = metric(tc)
    d = derive_metrics(s, 'run')
    middle = d['contacts'][1]
    assert middle['metrics']['imbalance_theory_percent']['value'] == pytest.approx(32.3232323232)
    assert middle['metrics']['imbalance_sample_percent']['value'] == pytest.approx(24.427480916)
    assert middle['source_contact_ids'] == [0, 1, 2]
    assert not d['contacts'][0]['metrics']['imbalance_theory_percent']['valid']
    assert not d['contacts'][-1]['metrics']['imbalance_theory_percent']['valid']


def test_duty_factor_uses_following_flight_and_belongs_to_contact_foot():
    s = measured('run').summary()
    d = derive_metrics(s, 'run')
    assert d['contacts'][0]['metrics']['duty_factor_percent']['value'] == pytest.approx(50)
    assert d['contacts'][0]['source_contact_ids'] == [0, 1]
    assert s['bilateral']['records']['cycles'][0]['metrics']['stance_phase_percent']['value'] == pytest.approx(25)
    assert not d['contacts'][-1]['metrics']['duty_factor_percent']['valid']


def test_acceleration_has_two_interval_denominator_and_never_bridges_gap():
    s = measured('run').summary()
    for row, speed in zip(s['steps'], [1., 2.]):
        row['time_s'] = metric(.5)
        row['speed_m_s'] = metric(speed)
    assert derive_metrics(s, 'run')['steps'][1]['metrics']['acceleration_m_s2']['value'] == pytest.approx(1.)
    s['steps'][0]['time_s'] = metric(reason='frame_gap')
    d = derive_metrics(s, 'run')
    assert not d['steps'][1]['metrics']['acceleration_m_s2']['valid']
    assert not d['contacts'][1]['metrics']['imbalance_theory_percent']['valid']


def test_missing_flight_is_not_zero_and_no_mutation():
    s = measured('run').summary()
    s['steps'][0]['flight_s'] = metric(reason='flight_not_observed')
    before = deepcopy(s)
    d = derive_metrics(s, 'run')
    assert s == before
    assert not d['steps'][0]['metrics']['flight_height_m']['valid']
    s['steps'][0]['flight_s'] = metric(0.)
    assert derive_metrics(s, 'run')['steps'][0]['metrics']['flight_height_m']['value'] == 0


def test_diff_is_signed_left_referenced_and_acceleration_has_no_relative_stats():
    def rows(code, left, right):
        return [{'side': side, 'source_ref': str(i), 'metrics': {code: metric(x)}}
                for i, (side, x) in enumerate([('left', left)]*3 + [('right', right)]*3)]
    stats = _statistics(rows('contact_time_s', 2., 1.), 'contact_time_s')
    assert stats['diff_percent']['value'] == 50
    assert stats['si_percent']['value'] == pytest.approx(200/3)
    assert _statistics(rows('contact_time_s', 1., 2.), 'contact_time_s')['diff_percent']['value'] == -100
    stats = _statistics(rows('acceleration_m_s2', -1., 1.), 'acceleration_m_s2')
    assert stats['difference']['value'] == -2
    assert not stats['si_percent']['valid'] and not stats['diff_percent']['valid']
    assert stats['right']['cv_percent'] is None


def test_saved_v1_bilateral_is_kept_without_recalculation():
    from config.overground_running_report import OvergroundRunningReport
    from reporting.ground_bilateral import comparison_rows
    s = measured('run').summary()
    snapshot = deepcopy(s['bilateral'])
    snapshot['version'] = 'ground_bilateral_v1'
    snapshot.pop('derived_formulas')
    for stats in snapshot['statistics'].values():
        stats.pop('diff_percent')
    s['bilateral'] = snapshot
    restored = OvergroundRunningReport(running_summary=deepcopy(s))
    assert restored.running_summary['bilateral'] == snapshot
    assert all(row['diff_percent'] is None for row in comparison_rows(restored.running_summary))


def test_pdf_and_spreadsheet_include_frozen_new_values():
    from reporting.pdf import report_html
    from reporting.excel import build_report_workbook
    p = measured('run')
    report = p.build_report('manual')
    text = report_html(report, title='地面跑步', stats=[], reason='手动结束', detailed=True)
    assert '腾空估计高度' in text and 'Diff%' in text and 'Imb（理论分母）' in text
    book = build_report_workbook(report)
    assert '足内阶段证据' in book.sheetnames and '足内形状' in book.sheetnames
    rows = list(book['左右统计'].values)
    columns = rows[0]
    item = next(dict(zip(columns, row)) for row in rows[1:] if row[0] == 'flight_height_m')
    expected = report.running_summary['bilateral']['statistics']['flight_height_m']
    assert item['left_mean'] == expected['left']['mean']
    assert item['diff_percent'] == expected['diff_percent']['value']
    book.close()
