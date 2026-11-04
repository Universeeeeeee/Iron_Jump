from copy import deepcopy

import pytest

from tests.test_overground_walking import processor as walking_processor, walk
from tests.test_overground_running import processor as running_processor, run


def measured(mode, side='Left'):
    if mode == 'walk':
        p = walking_processor(8, starting_foot=side, stop_type='Software command')
        walk(p, [(100 + 500*i, 800 + 500*i, .35 + .6*i) for i in range(8)], 4400)
    else:
        p = running_processor(8, starting_foot=side)
        run(p, [(100 + 300*i, 250 + 300*i, .3 + .5*i) for i in range(8)], 2600)
    return p


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_bilateral_support_is_the_reference_foot_not_cycle_occupancy(mode):
    p = measured(mode)
    s = p.summary()
    b = s['bilateral']
    c = b['records']['cycles'][1]['metrics']
    if mode == 'walk':
        expected = {'gait_cycle_s': 1., 'stance_phase_s': .7, 'swing_phase_s': .3,
                    'single_support_s': .3, 'total_double_support_s': .4,
                    'load_response_s': .2, 'pre_swing_s': .2}
    else:
        expected = {'gait_cycle_s': .6, 'stance_phase_s': .15, 'swing_phase_s': .45,
                    'single_support_s': .15, 'total_double_support_s': 0.,
                    'load_response_s': 0., 'pre_swing_s': 0.}
    for key, number in expected.items():
        assert c[key]['valid'], (key, c[key])
        assert c[key]['value'] == pytest.approx(number)
    assert c['stance_phase_percent']['value'] + c['swing_phase_percent']['value'] == pytest.approx(100)
    assert b['records']['cycles'][0]['metrics']['single_support_s']['missing_reason'] == 'entry_support_not_observed'
    assert b['statistics']['contact_time_s']['left']['count'] == 4
    assert b['statistics']['step_time_s']['left']['count'] == 3
    assert b['statistics']['step_time_s']['right']['count'] == 4
    assert not b['records']['steps'][0]['metrics']['step_time_percent']['valid']
    assert b['records']['steps'][1]['metrics']['step_time_percent']['value'] == pytest.approx(50)
    assert b['statistics']['contact_time_s']['si_percent']['value'] == pytest.approx(0)
    assert p.summary() == s


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_switching_starting_foot_swaps_statistics_without_changing_measurements(mode):
    left, right = (measured(mode, side).summary()['bilateral'] for side in ('Left', 'Right'))
    for code, stats in left['statistics'].items():
        other = right['statistics'][code]
        assert stats['left'] == other['right']
        assert stats['right'] == other['left']
        assert stats['all'] == other['all']
        assert stats['si_percent'] == other['si_percent']


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_undefined_side_keeps_overall_results_without_inventing_left_right(mode):
    s = measured(mode, 'Not defined').summary()['bilateral']['statistics']['contact_time_s']
    assert s['all']['count'] == s['unknown']['count'] == 8
    assert s['left']['count'] == s['right']['count'] == 0
    assert not s['si_percent']['valid']


def test_spatial_exclusion_does_not_renumber_side_or_invalidate_time():
    from engine.ground_bilateral import build_bilateral
    s = measured('walk').summary()
    s['steps'][1]['length_m'] = None
    b = build_bilateral(s, 'walk', 'Left')
    assert b['records']['steps'][1]['side'] == 'left'
    assert b['records']['steps'][2]['side'] == 'right'
    assert b['statistics']['step_time_s']['left']['count'] == 3
    assert b['statistics']['step_length_m']['left']['count'] == 2


def test_missing_release_does_not_use_report_completion_estimates():
    from engine.ground_bilateral import build_bilateral, metric
    from config.overground_running_report import OvergroundRunningReport
    s = deepcopy(measured('run').summary())
    s['contacts'][2]['contact_s'] = metric(reason='lift_not_observed')
    s['contacts'][2]['lift_s'] = metric(reason='lift_not_observed')
    s['contacts'][2]['lift_sample'] = None
    s['bilateral'] = build_bilateral(s, 'run', 'Left')
    before = deepcopy(s['bilateral'])
    report = OvergroundRunningReport(running_summary=s)
    assert report.running_summary['bilateral'] == before
    assert before['statistics']['contact_time_s']['left']['count'] == 3
    assert not before['records']['cycles'][2]['metrics']['stance_phase_s']['valid']


def test_zero_reference_and_single_sample_are_missing_not_perfect_symmetry():
    from engine.ground_bilateral import _statistics, metric
    rows = [{'source_ref': str(i), 'side': side, 'metrics': {'x': metric(x)}}
            for i, (side, x) in enumerate([('left', 0)] * 3 + [('right', 0)] * 3)]
    stats = _statistics(rows, 'x')
    assert stats['left']['mean'] == 0
    assert stats['left']['cv_percent'] is None
    assert stats['si_percent']['missing_reason'] == 'zero_reference'
    assert _statistics(rows[:1], 'x')['left']['std'] is None


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_snapshot_roundtrip_excel_ui_and_agent_share_the_same_results(tmp_path, qtbot, mode):
    from data.subject_store import SubjectStore
    from reporting.repository import ReportRepository
    from reporting.excel import build_report_workbook
    from reporting.ground_bilateral import comparison_rows
    from ui.views.report_view import ReportView
    from qtpy.QtWidgets import QTextBrowser
    from openpyxl import load_workbook
    p = measured(mode)
    report = p.build_report('manual')
    key = 'walking_summary' if mode == 'walk' else 'running_summary'
    snapshot = deepcopy(getattr(report, key)['bilateral'])
    store = SubjectStore(tmp_path / 'bilateral.sqlite3')
    sid = store.record_session(None, p.config, report)
    restored = store.get_session(sid).report
    assert getattr(restored, key)['bilateral'] == snapshot
    package = ReportRepository(store).get_package(sid)
    assert package.payload.bilateral == snapshot
    from reporting.observation import ObservationBuilder
    from reporting.builders import ReportManifestBuilder
    from reporting.models import DataScopeAvailability, DataAccessScope
    observation = ObservationBuilder().build(package, ReportManifestBuilder().build(package),
        DataScopeAvailability(), DataAccessScope(), ())
    for code, item in snapshot['statistics'].items():
        observed = observation.ground_bilateral['statistics'][code]
        assert observed['si_percent'] == item['si_percent']
        assert observed['left']['mean'] == item['left']['mean']
    for rs, kind in zip(package.record_sets, ('contacts', 'steps', 'cycles')):
        for record, source in zip(rs.records, snapshot['records'][kind]):
            for code, metric in source['metrics'].items():
                assert record.values[code].value == metric['value']
    expected = list(comparison_rows(getattr(restored, key)))
    book = build_report_workbook(restored)
    path = tmp_path / 'bilateral.xlsx'
    book.save(path)
    book.close()
    book = load_workbook(path, read_only=True, data_only=True)
    rows = iter(book['左右统计'].values)
    columns = next(rows)
    for raw, wanted in zip(rows, expected):
        row = dict(zip(columns, raw))
        assert row['metric'] == wanted['metric']
        for name in ('left_mean', 'right_mean', 'si_percent'):
            assert row[name] == pytest.approx(wanted[name]) if wanted[name] is not None else row[name] is None
    book.close()
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(restored)
    text = '\n'.join(widget.toPlainText() for widget in view.findChildren(QTextBrowser))
    assert '左右参数（有效观测）' in text
    assert '本侧单支撑时间' in text
    assert 'ground_bilateral_v2' in text


def test_legacy_snapshot_is_not_silently_recomputed():
    from tests.report_export_fixtures import export_reports
    from reporting.excel import build_report_workbook
    from reporting.ground_bilateral import bilateral_html
    for mode, report in export_reports().items():
        if mode not in ('walking', 'overground_running'):
            continue
        s = getattr(report, 'walking_summary', None) or report.running_summary
        assert 'bilateral' not in s
        assert '历史记录未包含' in bilateral_html(s)
        book = build_report_workbook(report)
        assert '左右统计' not in book.sheetnames
        book.close()


def test_percentages_use_individual_cycle_denominators():
    from engine.ground_bilateral import build_bilateral
    p = walking_processor(8, starting_foot='Left', stop_type='Software command')
    walk(p, [(100, 750, .4), (600, 1250, 1.), (1100, 1850, 1.6),
             (1800, 2450, 2.2), (2500, 3050, 2.8)], 3200)
    b = build_bilateral(p.summary(), 'walk', 'Left')
    times = b['statistics']['stance_phase_s']['left']
    cycles = b['statistics']['gait_cycle_s']['left']
    percents = b['statistics']['stance_phase_percent']['left']
    assert percents['mean'] == pytest.approx((65 + 100*.75/1.4)/2)
    assert percents['mean'] != pytest.approx(100 * times['mean'] / cycles['mean'])


def test_discontinuity_does_not_create_cycles_or_restore_anatomical_side():
    p = running_processor(8, starting_foot='Left')
    s = run(p, [(100 + 300*i, 250 + 300*i, .3 + .5*i) for i in range(8)], 2600, skip={900})
    for row, source in zip(s['bilateral']['records']['cycles'], s['cycles']):
        if row['metrics']['gait_cycle_s']['valid']:
            a, z = (s['contacts'][source[key]] for key in ('from_id', 'to_id'))
            assert a['epoch'] == z['epoch']
    assert s['bilateral']['statistics']['contact_time_s']['unknown']['count'] > 0
