"""Batch 3: time evidence, conditional release and retained competition."""
from copy import deepcopy
import pytest
from tests.test_ground_candidate_groups import make, feed, field_replay


def recovered(mode, competing=False):
    p = make(mode)
    for n in range(450):
        groups = [(40,41),(44,45)] if n == 100 else [(40,46)] if 101 <= n < 110 else [(40,60)] if 110 <= n < 350 else []
        if competing and 200 <= n < 300:
            groups += [(63,63)]
        if competing and 300 <= n < 350:
            groups = [(40,63)]
        feed(p,n,groups)
    return p


@pytest.mark.parametrize('mode', ['walk','run'])
def test_conditional_release_uses_complete_unchanged_source_cohort(mode):
    p = recovered(mode)
    r = p.build_report('manual')
    s = r.walking_summary if mode == 'walk' else r.running_summary
    row = next(c for c in s['contacts'] if c['id'] == 0)
    assert r.touch_count == 1 and r.lift_count == 1
    assert row['contact_s']['valid'] and row['contact_s']['value'] == pytest.approx(.25)
    assert row['metric_evidence']['lift']['basis'] == 'conditional_group_clear'
    assert row['metric_evidence']['lift']['source_ids'] == [0,1]
    assert s['valid_contact_durations'] == 1
    assert not (row.get('position_known', False) if mode == 'walk' else row['toe_m']['valid'])


@pytest.mark.parametrize('mode', ['walk','run'])
def test_later_competitor_keeps_landing_but_blocks_release_and_duration(mode):
    p = recovered(mode, True)
    r = p.build_report('manual')
    s = r.walking_summary if mode == 'walk' else r.running_summary
    row = s['contacts'][0]
    assert r.touch_count == 1 and r.lift_count == 0
    assert not row['lift_s']['valid'] and not row['contact_s']['valid']
    assert row['metric_evidence']['lift']['missing_reason'] == 'competing_source'


@pytest.mark.parametrize('mode', ['walk','run'])
@pytest.mark.parametrize('damage', ['gap','unreliable','interrupted'])
def test_group_metric_evidence_rejects_missing_samples_or_unobserved_clear(mode, damage):
    p = recovered(mode)
    g = next(g for g in p._ownership_groups if g.get('recovery'))
    if damage == 'gap':
        g['valid_sample_intervals'] = [[100,200],[201,350]]
    elif damage == 'unreliable':
        g['observation_runs'][0][3] = False
    else:
        g['tracking_end_reason'] = 'frame_gap'
    r = p.build_report('manual')
    assert r.touch_count == 1 and r.lift_count == 0


@pytest.mark.parametrize('field_replay', ['walk','run'], indirect=True)
def test_field_time_and_support_use_separate_dependencies(field_replay):
    mode,p,_ = field_replay
    ledger = deepcopy(p.touch_events)
    s = p.summary()
    assert p.touch_events == ledger
    if mode == 'walk':
        assert [(r['from_id'],r['to_id']) for r in s['steps']] == [
            (0,3),(3,4),(4,5),(5,6),(8,9),(9,10),(10,11),(11,12),(12,13)]
        # The 45564 source still blocks the 44935 -> 45637 relationship.
        assert (6,8) not in [(r['from_id'],r['to_id']) for r in s['steps']]
        assert s['valid_cycles'] == 7 and s['valid_support_cycles'] == 4
        origin = min(c['touch_sample'] for c in s['contacts'] if c['touch_sample'] is not None)
        cycles = {(round(origin+r['start_s']*1000),round(origin+r['end_s']*1000)):r for r in s['cycles']}
        first = cycles[43562,44935]
        assert first['single_support_s'] == pytest.approx(.976)
        assert first['double_support_s'] == pytest.approx(.397)
        assert cycles[47722,49151]['single_support_s'] is None
        assert cycles[47000,48424]['single_support_s'] is None
        spatial_pairs = {(r['from_id'], r['to_id']) for r in s['steps'] if r['length_m'] is not None}
        assert spatial_pairs == {(0,3), (3,4), (4,5), (8,9), (9,10), (12,13)}
        assert s['valid_step_lengths'] == len(spatial_pairs)
        distances = [r for r in s['steps'] if r['length_m'] is not None]
        assert s['walking_speed_m_s'] == pytest.approx(sum(r['length_m'] for r in distances)/sum(r['time_s'] for r in distances))
    else:
        valid = [r for r in s['steps'] if r['time_s']['valid']]
        assert len(valid) == 7 and s['valid_cycles'] == 5
        assert s['valid_contact_durations'] == 8
        assert s['valid_support_cycles'] == 5
        first = s['cycles'][0]
        assert first['duration_s']['value'] == pytest.approx(.829)
        assert first['single_support_s']['value'] == pytest.approx(.756)
        assert first['double_support_s']['value'] == pytest.approx(.009)
        assert first['flight_s']['value'] == pytest.approx(.064)
        for r in s['cycles']:
            if r['single_support_s']['valid']:
                assert sum(r[k]['value'] for k in ('single_support_s','double_support_s','flight_s')) == pytest.approx(r['duration_s']['value'])
        mixed = next(r for r in s['contacts'] if r['touch_sample'] == 103505)
        assert mixed['touch_s']['valid'] and not mixed['lift_s']['valid']
        # Complete owned spatial windows restore these pairs; the long source stays unknown.
        spatial = [r for r in s['steps'] if r['length_m']['valid']]
        assert {(r['from_id'], r['to_id']) for r in spatial} == {
            (0,5), (5,9), (11,16), (16,18), (18,19), (19,20)}
        assert s['valid_step_lengths'] == s['valid_step_speeds'] == len(spatial)
        assert s['running_speed_m_s'] == pytest.approx(
            sum(r['length_m']['value'] for r in spatial) / sum(r['time_s']['value'] for r in spatial))


def test_recovered_group_cannot_absorb_remote_unknown_occupant():
    p = make('run')
    for n in range(450):
        groups = [(40,41),(44,45)] if n == 100 else [(40,46)] if 101 <= n < 110 else [(40,60)] if 110 <= n < 350 else []
        if 200 <= n < 212:
            groups += [(200,201)]
        feed(p,n,groups)
    assert any(g.get('recovery') for g in p._ownership_groups)
    support, reason = p._support(100,350,0)
    assert support is None and reason == 'unconfirmed_narrow_fragment'


@pytest.mark.parametrize('mode', ['walk','run'])
def test_conditional_metrics_survive_consumers_without_restoring_position(mode, qtbot):
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from reporting.excel import build_report_workbook
    from ui.views.report_view import ReportView
    from qtpy.QtWidgets import QTextBrowser
    report = recovered(mode).build_report('manual')
    restored = _report_from_detail(_report_detail(report))
    s = restored.walking_summary if mode == 'walk' else restored.running_summary
    assert s['contacts'][0]['contact_s']['valid']
    package = ReportDataPackageBuilder().build(restored, ReportContextInput(session_id=1,test_type='Sprint and Gait Test' if mode=='walk' else 'Overground Running Test'))
    contact = package.record_sets[0].records[0]
    assert contact.status.validity == 'valid'
    assert contact.values['contact_time_s'].value == pytest.approx(.25)
    scope = next(f for f in package.quality_flags if f.code == 'ground_measurement_scope')
    assert scope.details['event_publications'] == s['event_publications']
    assert scope.details['event_audit'] == s['event_audit']
    book = build_report_workbook(restored)
    if mode == 'walk':
        assert 'Walking event_audit' in book.sheetnames
        assert 'conditional_group_clear' in str(list(book['Walking contacts'].values))
    else:
        assert 'conditional_group_clear' in str(list(book['Running contacts'].values))
    book.close()
    view = ReportView(); qtbot.addWidget(view); view.load_report(restored)
    assert any((str(s['contacts'][0]['lift_s']['value']) if mode == 'walk' else '0.2500')
               in b.toPlainText() for b in view.findChildren(QTextBrowser))


@pytest.mark.parametrize('mode', ['walk','run'])
def test_flush_repeated_reports_and_final_snapshot_do_not_republish(mode, qtbot):
    from engine.overground_session import OvergroundSession
    from tests.test_ground_candidate_groups import make
    p = recovered(mode)
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    session.processor = p
    seen=[]; session.snapshot.connect(seen.append)
    session.halt()
    first=session.build_report('manual')
    ledger=deepcopy(p.touch_events);audit=deepcopy(p.event_audit)
    second=session.build_report('manual')
    assert p.touch_events == ledger and p.event_audit == audit
    s = second.walking_summary if mode == 'walk' else second.running_summary
    assert seen[-1]['walking' if mode=='walk' else 'running'] == s
    assert first.touch_count == second.touch_count == seen[-1]['touch_count'] == 1
    assert first.lift_count == second.lift_count == 1


@pytest.mark.parametrize('mode', ['walk','run'])
def test_conditional_support_uses_foot_intervals_not_fragment_counts(mode):
    from dataclasses import replace
    p = make(mode)
    p.config = replace(p.config, stop_threshold_s=10)
    for n in range(850):
        groups = [(40,41),(44,45)] if n == 100 else [(40,46)] if 101 <= n < 110 else [(40,60)] if 110 <= n < 350 else []
        if 300 <= n < 550:
            groups += [(100,120)]
        if 500 <= n < 750:
            groups += [(160,180)]
        feed(p,n,groups)
    s = p.summary()
    assert s['valid_steps'] == 2 and s['valid_cycles'] == s['valid_support_cycles'] == 1
    cycle = s['cycles'][0]
    scalar = lambda k: cycle[k] if mode == 'walk' else cycle[k]['value']
    assert scalar('single_support_s') == pytest.approx(.35)
    assert scalar('double_support_s') == pytest.approx(.05)


@pytest.mark.parametrize('mode', ['walk','run'])
def test_manual_end_before_group_clear_keeps_lift_unknown(mode):
    p = make(mode)
    for n in range(250):
        groups = [(40,41),(44,45)] if n == 100 else [(40,46)] if 101 <= n < 110 else [(40,60)] if n >= 110 else []
        feed(p,n,groups)
    report = p.build_report('manual')
    assert report.touch_count == 1 and report.lift_count == 0
