"""Closed non-step observations cannot corrupt measured gait relationships."""
from dataclasses import replace

import pytest

from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import uncertain_contact
from hardware.walking_preflight import PreparedDevice
from tests.test_overground_walking import processor, frame


def replay(*, pulse=None, end=800, filtered=False, bad=False, skip=(), segments=3, reverse=False):
    p = processor(segments, stop_type='Software command', starting_foot='Left')
    if bad:
        p.device = PreparedDevice(p.device.layout, 'test', -1, 0, 3000, bad_indices=(220,))
    optical = GroundStabilityFilter(p.device.layout, p.device.bad_indices)
    for n in range(end):
        if n in skip:
            continue
        bits = bytearray(len(p.positions))
        for start, stop, low, high in [(100,300,20,40), (220,500,85,105), (420,650,150,170)]:
            if start <= n < stop:
                bits[low:high+1] = b'\x01'*(high-low+1)
        if pulse:
            for low, high in pulse(n):
                bits[low:high+1] = b'\x01'*(high-low+1)
        if reverse:
            bits.reverse()
        raw = replace(frame(p.device.layout, n), contact_bits=bytes(bits))
        for f in optical.feed(raw) if filtered else [raw]:
            p.process(f, masked_contact=uncertain_contact(f, p.device.bad_indices))
    if filtered:
        for f in optical.flush():
            p.process(f, masked_contact=uncertain_contact(f, p.device.bad_indices))
    return p


@pytest.mark.parametrize('segments', [3, 8, 16])
@pytest.mark.parametrize('reverse', [False, True])
def test_isolated_sample_does_not_change_identity_adjacency_or_support(segments, reverse):
    baseline = replay(segments=segments, reverse=reverse).summary()
    p = replay(pulse=lambda n: [(220,220)] if n == 280 else [], segments=segments, reverse=reverse)
    s = p.summary()
    assert s['valid_steps'] == baseline['valid_steps'] == 2
    assert s['valid_cycles'] == baseline['valid_cycles'] == 1
    assert [c['side'] for c in s['contacts']] == ['left','right','left']
    assert s['single_support_s'] == baseline['single_support_s']
    assert s['double_support_s'] == baseline['double_support_s']
    decisions = s['candidate_decisions']
    assert len(decisions) == 1
    assert decisions[0]['outcome'] == 'excluded_nonstep'
    assert decisions[0]['first_sample'] == decisions[0]['last_sample'] == 280


def test_generic_isolated_sample_is_retained_but_skipped_in_step_sequence():
    p = processor(stop_type='Software command', starting_foot='Left')
    for n in range(800):
        ranges = [(.2,.4)] if 100 <= n < 250 else [(.8,1.0)] if 400 <= n < 550 else [(1.4,1.6)] if 650 <= n < 750 else []
        if n == 300:
            ranges += [(p.positions[220],p.positions[220])]
        p.process(frame(p.device.layout, n, ranges))
    assert len(p.contacts) == 4
    assert p.contacts[1].candidate_outcome == 'excluded_nonstep'
    s = p.summary()
    assert [(x['from_id'],x['to_id']) for x in s['steps']] == [(0,2),(2,3)]
    assert s['valid_cycles'] == 1
    assert [c.side for c in p.contacts if c.confirmed] == ['left','right','left']
    from tools.audit_walking_evidence import step_decisions, cycle_decisions
    assert [(x['from_id'],x['to_id']) for x in step_decisions(s) if x['included']] == [(0,2),(2,3)]
    assert [x['contact_ids'] for x in cycle_decisions(s,p.origin) if x['included']] == [[0,2,3]]


def test_excluded_tail_sample_does_not_extend_passage_duration():
    baseline = replay().summary()
    p = replay(pulse=lambda n: [(220,220)] if n == 700 else [])
    assert p.summary()['duration_s'] == baseline['duration_s'] == pytest.approx(.55)
    assert p.last_occupied == 649 / 1000


@pytest.mark.parametrize('duration,width', [(2,1),(1,2),(20,12)])
def test_larger_or_repeated_short_candidates_remain_unresolved(duration,width):
    p = replay(pulse=lambda n: [(220,220+width-1)] if 280 <= n < 280+duration else [])
    s = p.summary()
    assert s['valid_steps'] < 2
    assert s['valid_cycles'] == 0
    assert not any(x['outcome']=='excluded_nonstep' for x in s['candidate_decisions'])


@pytest.mark.parametrize('restriction', ['bad','gap','stop','boundary'])
def test_missing_quality_or_release_proof_prevents_nonstep_exclusion(restriction):
    beam = 221 if restriction=='bad' else 0 if restriction=='boundary' else 220
    p = replay(pulse=lambda n: [(beam,beam)] if n == 280 else [],
               bad=restriction=='bad', skip={281} if restriction=='gap' else (),
               end=282 if restriction=='stop' else 800)
    report = p.build_report('manual')
    assert not any(x['outcome']=='excluded_nonstep' for x in report.walking_summary['candidate_decisions'])
    assert report.walking_summary['valid_cycles'] == 0


def test_narrow_return_before_release_retains_original_touch_and_clear_interval():
    p = processor(stop_type='Software command')
    for n in range(600):
        bits = bytearray(len(p.positions))
        if 100 <= n < 350:
            bits[20:41] = b'\x01'*21
        if n==220:
            bits[85] = 1
        if 230 <= n < 450:
            bits[85:106] = b'\x01'*21
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)))
    assert len(p.contacts)==2
    assert p.contacts[1].start==pytest.approx(.22)
    assert p.contacts[1].merged_interruptions == [
        {'start_sample':221,'end_sample':230,'reason':'release_debounce'}]
    assert not any(x['outcome']=='excluded_nonstep' for x in p.summary()['candidate_decisions'])


def test_healthy_contact_span_is_reported_while_earlier_identity_is_pending():
    p = processor(stop_type='Software command', starting_foot='Left')
    for n in range(351):
        ranges = [(.33,.37)] if 100 <= n < 400 else []
        if 200 <= n < 300:
            ranges += [(.85,1.05)]
        p.process(frame(p.device.layout,n,ranges))
    s=p.summary()
    assert p.origin is None and not p.contacts[1].label
    assert s['mean_contact_s']==pytest.approx(.1)
    assert s['valid_contact_durations']==1
    assert s['contacts'][1]['touch_sample']==200
    assert s['contacts'][1]['lift_sample']==300
    assert s['contacts'][1]['confirmed_sample']==259
    assert s['steps']==[] and s['cycles']==[]


def test_filtered_single_raw_sample_does_not_claim_new_measurement_candidate():
    p = replay(pulse=lambda n: [(220,220)] if n==280 else [],filtered=True)
    assert p.summary()['valid_steps']==2
    assert p.summary()['candidate_decisions']==[]  # current front end removed it


@pytest.mark.parametrize('pulse_samples', [(2900,), (2900,2905), (2900,2905,2912)])
def test_excluded_tail_sample_does_not_restart_exit_clear_deadline(pulse_samples):
    from tests.test_overground_walking import CONTACTS
    def run(pulse):
        p = processor()
        route = CONTACTS + [(2100,2800,2.75)]
        for n in range(3600):
            ranges = [(x-.1,x+.1) for a,b,x in route if a <= n < b]
            if pulse and n in pulse_samples:
                beam = 220 + 10 * pulse_samples.index(n)
                ranges.append((p.positions[beam],p.positions[beam]))
            p.process(frame(p.device.layout,n,ranges))
            if p.finished_reason:
                return p,n
        pytest.fail('passage did not finish')
    baseline, finish = run(False)
    measured, pulse_finish = run(True)
    assert measured.finished_reason == baseline.finished_reason == 'passage_complete'
    assert pulse_finish == finish
    assert measured.summary()['duration_s'] == baseline.summary()['duration_s']


def test_pending_span_and_candidate_decisions_survive_report_and_excel(qtbot):
    from io import BytesIO
    from openpyxl import load_workbook
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.builders import ReportDataPackageBuilder
    from reporting.excel import build_report_workbook
    from reporting.models import ReportContextInput
    from qtpy.QtWidgets import QTextBrowser
    from ui.views.report_view import ReportView

    p = processor(stop_type='Software command',starting_foot='Left')
    for n in range(351):
        ranges = [(.33,.37)] if n >= 100 else []
        if 200 <= n < 300:
            ranges.append((.85,1.05))
        p.process(frame(p.device.layout,n,ranges))
    report = _report_from_detail(_report_detail(p.build_report('manual')))
    package = ReportDataPackageBuilder().build(report,ReportContextInput(session_id=1,test_type='Sprint and Gait Test'))
    contact = package.record_sets[0].records[1]
    assert contact.status.validity == 'valid' and contact.status.inclusion == 'included'
    assert contact.values['contact_time_s'].value == pytest.approx(.1)
    assert contact.side == 'unknown'
    fact = next(f for f in package.scalar_facts if f.metric_code == 'contact_time_s')
    assert fact.sample_count == 1 and fact.value == pytest.approx(.1)
    assert package.record_sets[1].records == ()

    report = _report_from_detail(_report_detail(replay(pulse=lambda n: [(220,220)] if n==280 else []).build_report('manual')))
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(report)
    detail = next(x for x in view.findChildren(QTextBrowser) if '接触记录' in x.toPlainText())
    assert '已排除非步候选' in detail.toPlainText()
    book = build_report_workbook(report)
    stream = BytesIO()
    book.save(stream)
    book.close()
    stream.seek(0)
    saved = load_workbook(stream)
    decisions = list(saved['Walking candidate_decisions'].values)
    headers = decisions[0]
    assert decisions[1][headers.index('first_sample')] == 280
    assert decisions[1][headers.index('outcome')] == 'excluded_nonstep'
    saved.close()


@pytest.mark.parametrize('invalid_kind', ['invalid_bits','filter_tail'])
def test_unknown_release_sample_preserves_unresolved_diagnostic(invalid_kind):
    p = processor(stop_type='Software command')
    source = []
    for n in range(400):
        bits = bytearray(len(p.positions))
        if n >= 100:
            bits[20:41] = b'\x01'*21
        if n == 280:
            bits[220] = 1
        f = replace(frame(p.device.layout,n),contact_bits=bytes(bits))
        if n == 286:
            f = replace(f,valid_bits=b'\x00'*len(bits)) if invalid_kind=='invalid_bits' else replace(
                f,quality_flags=('unconfirmed_filter_tail',))
        source.append(f)
        before = (f.contact_bits,f.valid_bits,f.wire_payload)
        p.process(f)
        assert before == (f.contact_bits,f.valid_bits,f.wire_payload)
    decisions = p.summary()['candidate_decisions']
    pulse = next(x for x in decisions if x['first_sample']==280)
    assert pulse['outcome']=='unresolved' and pulse['closed_sample'] is None
    assert pulse['reason']=='invalid_sample'
    assert source[280].contact_bits[220] == 1


def test_excluded_tail_does_not_restore_clear_proof_across_acquisition_gap():
    from tests.test_overground_walking import CONTACTS
    p = processor()
    route = CONTACTS + [(2100,2800,2.75)]
    for n in range(3600):
        if n == 2950:
            continue
        ranges = [(x-.1,x+.1) for a,b,x in route if a <= n < b]
        if n in {2900,3000}:
            ranges.append((p.positions[220],p.positions[220]))
        p.process(frame(p.device.layout,n,ranges))
        if n == 3300:
            assert p.finished_reason is None
        if p.finished_reason:
            break
    assert p.finished_reason=='passage_complete' and n==3451


def test_near_deadline_candidate_must_close_before_automatic_finish():
    from tests.test_overground_walking import CONTACTS
    p = processor()
    route = CONTACTS + [(2100,2800,2.75)]
    for n in range(3400):
        ranges = [(x-.1,x+.1) for a,b,x in route if a <= n < b]
        if n==3295:
            ranges.append((p.positions[220],p.positions[220]))
        p.process(frame(p.device.layout,n,ranges))
        if n==3300:
            assert p.finished_reason is None
            assert p.summary()['candidate_decisions'][-1]['outcome']=='pending'
        if p.finished_reason:
            break
    assert n==3306 and p.finished_reason=='passage_complete'


def test_local_unknown_timeout_closes_candidate_as_unresolved():
    from tests.test_ground_local_observation import processor as local_processor, replay as local_replay, sample
    p = local_processor('walk')
    frames = [sample(n,[(.33,.37)] if 100 <= n < 250 else [],
                     [0] if 120 <= n < 140 else []) for n in range(300)]
    local_replay(p,frames)
    assert p.contacts[0].exclusion=='local_unknown_timeout'
    assert p.contacts[0].candidate_outcome=='unresolved'
    decision = next(x for x in p.summary()['candidate_decisions'] if x.get('contact_id')==0)
    assert decision['outcome']=='unresolved' and decision['reason']=='local_unknown_timeout'
    assert decision['closed_sample'] is None


def test_exact_sample_fields_do_not_round_a_bounded_estimate():
    from tests.test_ground_local_observation import processor as local_processor, replay as local_replay, sample
    p = local_processor('walk')
    local_replay(p,[sample(n,[(.2,.38)] if 100 <= n < 300 else [],
                           [0] if 98 <= n < 102 else []) for n in range(350)])
    assert p.contacts[0].start==pytest.approx(.0995)
    assert p.contacts[0].edge_estimates['touch']==[97,102]
    contact = p.summary()['contacts'][0]
    assert contact['touch_sample'] is None
    assert contact['lift_sample']==300
    assert contact['confirmed_sample'] is not None


def test_excel_keeps_owner_and_contact_ids_for_mixed_candidate_sources(qtbot):
    from reporting.excel import build_report_workbook
    def pulse(n):
        groups = [(220,220)] if n in {280,700} else []
        if 280 <= n < 285:
            groups += [(46,46)]
        elif 285 <= n < 300:
            groups += [(40,46)]
        return groups
    report = replay(pulse=pulse).build_report('manual')
    decisions = report.walking_summary['candidate_decisions']
    assert any(x.get('owner_id')==0 for x in decisions)
    assert any(x.get('contact_id')==3 for x in decisions)
    book = build_report_workbook(report)
    rows = list(book['Walking candidate_decisions'].values)
    headers = rows[0]
    assert 'owner_id' in headers and 'contact_id' in headers
    assert any(x[headers.index('owner_id')]==0 for x in rows[1:])
    assert any(x[headers.index('contact_id')]==3 for x in rows[1:])
    book.close()
