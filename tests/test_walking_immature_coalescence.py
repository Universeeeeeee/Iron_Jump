"""Local optical coalescence retains evidence without claiming a single foot."""
from dataclasses import replace
import pytest
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import uncertain_contact, masked_frame
from hardware.walking_preflight import PreparedDevice
from tests.test_overground_walking import processor, frame


def replay(*, anchored=False, kind='async', filtered=False, reverse=False, segments=3):
    p=processor(segments,stop_type='Software command',starting_foot='Left')
    if kind=='bad':
        p.device=PreparedDevice(p.device.layout,'test',-1,0,3000,bad_indices=(95,))
    optical=GroundStabilityFilter(p.device.layout,p.device.bad_indices)
    source=[]
    for n in range(800):
        if kind=='gap' and n==222:
            continue
        groups=[(20,40)] if anchored and 100 <= n < 450 else []
        second=220 if kind=='simultaneous' else 222
        join=235 if kind=='late' else 223
        if 220 <= n < join:
            groups += ([(85,89)] if kind=='wide' or kind=='shrink' and n==220
                       else [(85,85)] if kind=='single' else [(85,86)])
        if second <= n < join:
            groups += [(95,95)] if kind=='single' else [(95,96)]
        if join <= n < 500:
            groups += [(85,105)]
        if 520 <= n < 650:
            groups += [(150,170)]
        if 660 <= n < 750:
            groups += [(215,235)]
        bits=bytearray(len(p.positions))
        for low,high in groups:
            bits[low:high+1]=b'\x01'*(high-low+1)
        if reverse:
            bits.reverse()
        raw=replace(frame(p.device.layout,n),contact_bits=bytes(bits))
        source.append(raw.contact_bits)
        for measured in optical.feed(raw) if filtered else [raw]:
            p.process(measured,masked_contact=uncertain_contact(measured,p.device.bad_indices))
        assert raw.contact_bits==source[-1]
    if filtered:
        for measured in optical.flush():
            p.process(measured,masked_contact=uncertain_contact(measured,p.device.bad_indices))
    return p


@pytest.mark.parametrize('anchored',[False,True])
@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('segments',[3,8,16])
@pytest.mark.parametrize('filtered',[False,True])
def test_asynchronous_immature_coalescence_is_local_and_keeps_ambiguity(anchored,reverse,segments,filtered):
    p=replay(anchored=anchored,reverse=reverse,segments=segments,filtered=filtered)
    assert not any(i['code']=='ambiguous_contacts' for i in p.issues)
    group=next(c for c in p.contacts if round(c.start*1000)==220 and c.candidate_outcome!='associated_fragment')
    assert group.confirmed and group.start==pytest.approx(.220) and group.end==pytest.approx(.5)
    assert group.exclusion=='unresolved_coalescence'
    assert not group.touch_known and not group.position_known and group.side=='unknown'
    assert group.observed_samples==280  # no double votes from overlapping islands
    decisions=p.summary()['candidate_decisions']
    assert any(d['reason']=='immature_islands_coalesced' and d['first_sample']==222 for d in decisions)
    assert [(s['from_id'],s['to_id']) for s in p.summary()['steps']]==[(p.contacts[-2].id,p.contacts[-1].id)]
    if anchored:
        assert p.contacts[0].end==pytest.approx(.45) and p.contacts[0].touch_known
        assert p.summary()['valid_contact_durations']==3
    else:
        assert p.summary()['duration_s'] is None  # initial boundary has unresolved identity/count


@pytest.mark.parametrize('anchored',[False,True])
@pytest.mark.parametrize('kind',['simultaneous','late','wide','shrink','gap','bad'])
def test_coalescence_cannot_resolve_unproven_or_interrupted_foot_identity(anchored,kind):
    p=replay(anchored=anchored,kind=kind)
    assert not any(d['reason']=='immature_islands_coalesced' for d in p.summary()['candidate_decisions'])


def test_mature_optical_contact_with_unknown_initial_identity_can_anchor_new_island():
    p=processor(stop_type='Software command')
    for n in range(600):
        groups=[(20,40)] if 100 <= n < 500 else []
        if 280 <= n < 550:
            groups += [(85,105)]
        if n in {100,300}:
            groups += [(220,220)]
        bits=bytearray(len(p.positions))
        for low,high in groups:
            bits[low:high+1]=b'\x01'*(high-low+1)
        p.process(replace(frame(p.device.layout,n),contact_bits=bytes(bits)))
    assert not any(i['code']=='ambiguous_contacts' for i in p.issues if i['frame_index']==300)
    assert any(d['first_sample']==300 and d['outcome']=='excluded_nonstep' for d in p.summary()['candidate_decisions'])


def test_two_mature_feet_merging_still_break_continuity():
    p=processor(stop_type='Software command')
    for n in range(500):
        groups=[(20,40)] if 100 <= n < 200 else [(20,40),(50,70)] if 200 <= n < 300 else [(33,57)] if 300 <= n < 400 else []
        bits=bytearray(len(p.positions))
        for low,high in groups:
            bits[low:high+1]=b'\x01'*(high-low+1)
        p.process(replace(frame(p.device.layout,n),contact_bits=bytes(bits)))
    assert any(i['code']=='ambiguous_contacts' and i['frame_index']==300 for i in p.issues)


@pytest.mark.parametrize('filtered', [False, True])
def test_contact_and_private_first_islands_cannot_wash_out_unknown_identity(filtered):
    p = replay(kind='single', filtered=filtered)
    group = next(c for c in p.contacts if round(c.start * 1000) == 220)
    assert group.exclusion == 'unresolved_coalescence'
    assert not group.touch_known and not group.position_known
    assert any(d['first_sample'] == 222 and d['reason'] == 'immature_islands_coalesced'
               for d in p.summary()['candidate_decisions'])


def test_delayed_unresolved_group_cannot_supply_direction_or_false_turn():
    p = processor(stop_type='Software command')
    for n in range(1000):
        groups = [(20, 23)] if 100 <= n < 700 else []
        groups += ([(205, 205)] if 220 <= n < 223 else [])
        groups += ([(215, 215)] if 222 <= n < 223 else [])
        groups += ([(205, 225)] if 223 <= n < 500 else [])
        groups += ([(150, 170)] if 520 <= n < 850 else [])
        groups += ([(210, 230)] if 720 <= n < 950 else [])
        bits = bytearray(len(p.positions))
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)))
    assert p.finished_reason is None and p.direction == 1
    assert p.entry_position == pytest.approx((p.positions[150] + p.positions[170]) / 2)
    assert p.contacts[-1].confirmed and p.contacts[-1].end == pytest.approx(.950)


def test_two_footprints_can_cover_three_modules_without_being_noise():
    p = processor(3, stop_type='Software command')
    for n in range(500):
        groups = ([(85, 105)] if 100 <= n < 350 else []) + ([(181, 201)] if 200 <= n < 450 else [])
        bits = bytearray(len(p.positions))
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)))
    assert not p.issues and len(p.contacts) == 2
    assert all(c.confirmed and c.touch_known for c in p.contacts)
    assert p.summary()['valid_steps'] == 1


def test_unknown_group_remains_unknown_in_saved_report_package_and_excel(qtbot):
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from reporting.excel import build_report_workbook
    from qtpy.QtWidgets import QTextBrowser
    from ui.views.report_view import ReportView
    report = _report_from_detail(_report_detail(replay(kind='single').build_report('manual')))
    assert report.touch_count == report.walking_summary['valid_touches'] == 2
    assert report.lift_count == 2
    row = report.walking_summary['contacts'][0]
    assert row['touch_sample'] is None and row['lift_sample'] is None
    assert not row['touch_known'] and not row['position_known'] and row['side'] == 'unknown'
    package = ReportDataPackageBuilder().build(report, ReportContextInput(session_id=1, test_type='Sprint and Gait Test'))
    assert package.record_sets[0].records[0].values['contact_time_s'].state != 'present'
    view = ReportView(); qtbot.addWidget(view); view.load_report(report)
    detail = next(x for x in view.findChildren(QTextBrowser) if '接触记录' in x.toPlainText())
    assert '脚数与边界归属未决' in detail.toPlainText()
    book = build_report_workbook(report)
    rows = list(book['Walking candidate_decisions'].values)
    headers = rows[0]
    assert 'owner_id' in headers
    assert any(r[headers.index('owner_id')] == 0 and r[headers.index('first_sample')] == 222 for r in rows[1:])
    book.close()


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_first_group_contract_also_holds_with_one_module(filtered, reverse):
    p = processor(1, stop_type='Software command')
    optical = GroundStabilityFilter(p.device.layout)
    for n in range(800):
        groups = ([(5, 6)] if 220 <= n < 223 else []) + ([(15, 16)] if n == 222 else [])
        groups += [(5, 25)] if 223 <= n < 500 else []
        groups += [(40, 60)] if 520 <= n < 650 else []
        groups += [(70, 90)] if 660 <= n < 750 else []
        bits = bytearray(len(p.positions))
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        if reverse:
            bits.reverse()
        raw = replace(frame(p.device.layout, n), contact_bits=bytes(bits))
        for measured in optical.feed(raw) if filtered else [raw]:
            p.process(measured)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    assert not p.issues and p.summary()['valid_steps'] == 1
    group = p.contacts[0]
    assert group.start == pytest.approx(.220) and group.exclusion == 'unresolved_coalescence'
    assert not group.touch_known and not group.position_known


@pytest.mark.parametrize('kind', ['coalescence', 'mask'])
@pytest.mark.parametrize('healthy_start', [100, 130, 170])
@pytest.mark.parametrize('filtered', [False, True])
def test_duration_onset_depends_on_the_earliest_activity_not_confirmation_order(kind, healthy_start, filtered):
    p = processor(stop_type='Software command')
    if kind == 'mask':
        p.device = PreparedDevice(p.device.layout, 'test', -1, 0, 3000, bad_indices=(95,))
    optical = GroundStabilityFilter(p.device.layout, p.device.bad_indices)
    for n in range(700):
        groups = [(20, 40)] if healthy_start <= n < 350 else []
        if kind == 'mask':
            groups += [(85, 105)] if 130 <= n < 250 else []
        else:
            groups += [(85, 86)] if 130 <= n < 133 else []
            groups += [(95, 95)] if n == 132 else []
            groups += [(85, 105)] if 133 <= n < 250 else []
        groups += [(150, 170)] if 400 <= n < 550 else []
        bits = bytearray(len(p.positions))
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        raw = replace(frame(p.device.layout, n), contact_bits=bytes(bits))
        clean = masked_frame(raw, p.device.bad_indices)
        for measured in optical.feed(clean) if filtered else [clean]:
            p.process(measured, masked_contact=uncertain_contact(measured, p.device.bad_indices))
    if filtered:
        for measured in optical.flush():
            p.process(measured, masked_contact=uncertain_contact(measured, p.device.bad_indices))
    if kind == 'coalescence' and healthy_start == 130:
        assert [i['code'] for i in p.issues] == ['ambiguous_contacts']
    else:
        assert not p.issues or all(i['code'] == 'masked_contact_boundary' for i in p.issues)
    if healthy_start == 100:
        assert p.origin == pytest.approx(.100)
        assert p.summary()['duration_s'] == pytest.approx(.450)
    else:
        assert p.summary()['duration_s'] is None


@pytest.mark.parametrize('grows',[False,True])
def test_unowned_single_beam_waits_for_its_own_evidence_without_a_confirmed_anchor(grows):
    p=processor(stop_type='Software command')
    for n in range(500):
        groups=[(20,40)] if 100 <= n < 300 else []
        if 110 <= n < 400:
            groups += [(85,105)]
        if n==120 or grows and 120 <= n < 130:
            groups += [(220,220)]
        if grows and 130 <= n < 300:
            groups += [(220,240)]
        bits=bytearray(len(p.positions))
        for low,high in groups:
            bits[low:high+1]=b'\x01'*(high-low+1)
        p.process(replace(frame(p.device.layout,n),contact_bits=bytes(bits)))
    if grows:
        assert any(i['code']=='ambiguous_contacts' and i['frame_index']==130 for i in p.issues)
        assert not any(d['outcome']=='excluded_nonstep' for d in p.summary()['candidate_decisions'])
    else:
        assert not p.issues and len(p.contacts)==2
        assert p.summary()['valid_steps']==1
        assert any(d['first_sample']==120 and d['outcome']=='excluded_nonstep' for d in p.summary()['candidate_decisions'])
