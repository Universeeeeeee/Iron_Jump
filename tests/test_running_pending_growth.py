"""Growing unconfirmed optical sources stay local and never become foot truth."""
from dataclasses import replace

import pytest

from engine.modes.overground_running_processor import OvergroundRunningProcessor
from engine.overground_session import OvergroundSession
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice
from tests.test_overground_running import processor


def onset(kind, n):
    if kind == 'contact_pair':
        if n == 100:
            return [(22, 22)]
        if 101 <= n < 103:
            return [(20, 23)]
        if n == 103:
            return [(20, 23), (31, 31)]
        if n == 104:
            return [(20, 23), (27, 31)]
        if 105 <= n < 350:
            return [(19, 37)]
    else:
        if n == 100:
            return [(61, 64)]
        if n == 101:
            return [(58, 65)]
        if n == 102:
            return [(54, 54), (58, 65)]
        if 103 <= n < 350:
            return [(52, 70)]
    return []


def sample(p, n, groups, reverse=False):
    bits = bytearray(p.device.layout.bit_count)
    for low, high in groups:
        if reverse:
            low, high = len(bits) - 1 - high, len(bits) - 1 - low
        bits[low:high + 1] = b'\x01' * (high - low + 1)
    return SensorFrame(p.device.stream_id, p.device.layout, n, n, n + 1,
                       bytes(bits), b'\x01' * len(bits), b'')


@pytest.mark.parametrize('kind', ['contact_pair', 'private_pair'])
@pytest.mark.parametrize('segments', [1, 3, 8, 12])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('minimum', [20, 60])
def test_pending_growth_retains_unknown_group_and_later_independent_feet(
        qtbot, kind, segments, reverse, filtered, minimum):
    p = processor(segments, min_contact_time=minimum, starting_foot='Left',
                  stop_type='Software command')
    session = OvergroundSession(p.config, type(p)) if filtered else None
    if session:
        session.start_prepared(p.device)
    for n in range(850):
        groups = onset(kind, n)
        if 400 <= n < 550:
            groups += [(5, 18)] if kind == 'private_pair' else [(50, 65)]
        if 600 <= n < 750:
            groups += [(25, 40)] if kind == 'private_pair' else [(75, 89)]
        f = sample(p, n, groups, reverse)
        if session:
            session.on_frame(f)
        else:
            p.process(f)
    if session:
        session.halt()
        p = session.processor
    s = p.summary()
    assert not p.issues
    parent = next(c for c in p.contacts if c.start == 100 and c.problem == 'unresolved_coalescence')
    assert parent.end == 350 and parent.observed_samples == 250
    assert parent.confirmed and parent.candidate_outcome == 'unresolved_group'
    assert not parent.touch_known and parent.side == 'unknown' and not parent.label
    row = next(c for c in s['contacts'] if c['id'] == parent.id)
    assert all(not row[k]['valid'] for k in ('touch_s', 'lift_s', 'toe_m', 'contact_s'))
    sources = [x for x in s['candidate_decisions'] if x['reason'] == 'immature_islands_coalesced']
    assert len(sources) == 2 and {x['owner_id'] for x in sources} == {parent.id}
    assert {x['first_sample'] for x in sources} == ({100, 103} if kind == 'contact_pair' else {100, 102})
    assert s['record_count'] == len(p.contacts) and s['valid_touches'] == 2
    assert len([c for c in p.contacts if c.candidate_outcome != 'associated_fragment']) == 3
    assert s['steps'][-1]['time_s']['valid'] and s['steps'][-1]['time_s']['value'] == pytest.approx(.2)
    assert s['duration_s'] is None and p.origin == .4
    assert not p._exit_evidence
    report = p.build_report('manual')
    assert report.touch_count == 2 and report.lift_count == 2
    assert report.report_config_snapshot['algorithm'] == 'overground_running_v1.12'


@pytest.mark.parametrize('filtered', [False, True])
def test_pending_growth_keeps_remote_confirmed_anchor_object_and_own_span(qtbot, filtered):
    p = processor(3, min_contact_time=60, stop_type='Software command')
    session = OvergroundSession(p.config, type(p)) if filtered else None
    if session:
        session.start_prepared(p.device)
    for n in range(500):
        groups = onset('private_pair', n)
        if 20 <= n < 300:
            groups += [(110, 125)]
        f = sample(p, n, groups)
        if session:
            session.on_frame(f)
        else:
            p.process(f)
    if session:
        session.halt()
        p = session.processor
    assert not p.issues
    anchor = p.contacts[0]
    assert anchor.start == 20 and anchor.end == 300 and not anchor.interrupted
    assert p.summary()['contacts'][0]['contact_s']['value'] == pytest.approx(.28)
    assert p.summary()['contacts'][0]['contact_s']['valid']
    assert p.origin == .02


@pytest.mark.parametrize('segments,wire_order', [(3, (3, 1, 2)),
    (8, (8, 2, 6, 1, 4, 3, 5, 7))])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('filtered', [False, True])
def test_pending_growth_across_seam_uses_actual_geometry(qtbot, segments, wire_order, reverse, filtered):
    base = processor(segments, min_contact_time=60, stop_type='Software command')
    layout = DeviceLayout.linear(segments, wire_order=wire_order)
    p = OvergroundRunningProcessor(base.config, PreparedDevice(layout, 'running', -1, 0, 1000))
    session = OvergroundSession(p.config, type(p)) if filtered else None
    if session:
        session.start_prepared(p.device)
    for n in range(500):
        groups = [(a + 70, b + 70) for a, b in onset('contact_pair', n)]
        f = sample(p, n, groups, reverse)
        if session:
            session.on_frame(f)
        else:
            p.process(f)
    if session:
        session.halt()
        p = session.processor
    parent = p.contacts[0]
    assert not p.issues and parent.problem == 'unresolved_coalescence'
    assert parent.observed_samples == 250 and parent.end == 350
    assert p.summary()['valid_touches'] == 0 and p.summary()['duration_s'] is None


@pytest.mark.parametrize('kind', ['contact_pair', 'private_pair'])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('filtered', [False, True])
def test_only_later_independent_contacts_supply_a_valid_cycle(qtbot, kind, reverse, filtered):
    p = processor(3, min_contact_time=60, stop_type='Software command')
    session = OvergroundSession(p.config, type(p)) if filtered else None
    if session:
        session.start_prepared(p.device)
    for n in range(1300):
        groups = onset(kind, n)
        for start, low in ((400, 150), (700, 220), (1000, 260)):
            if start <= n < start + 150:
                groups += [(low, low + 20)]
        f = sample(p, n, groups, reverse)
        if session:
            session.on_frame(f)
        else:
            p.process(f)
    if session:
        session.halt()
        p = session.processor
    s = p.summary()
    assert not p.issues and s['valid_cycles'] == 1 and s['valid_steps'] == 2
    assert not s['cycles'][0]['duration_s']['valid']
    assert s['cycles'][-1]['duration_s']['valid']
    assert s['cycles'][-1]['duration_s']['value'] == pytest.approx(.6)
    assert s['duration_s'] is None


@pytest.mark.parametrize('restriction', ['mature', 'simultaneous', 'wide_history',
    'shrink', 'boundary', 'gap', 'invalid', 'bad_margin', 'masked', 'third_wide',
    'late_join', 'far', 'third_source', 'unknown'])
def test_pending_growth_rejects_unproven_or_nonlocal_association(restriction):
    p = processor(3, min_contact_time=60, stop_type='Software command')
    if restriction in {'bad_margin', 'masked'}:
        p = OvergroundRunningProcessor(p.config, PreparedDevice(p.device.layout,
            'running', -1, 0, 1000, bad_indices=(18,)))
    for n in range(500):
        if restriction == 'gap' and n == 104:
            continue
        groups = onset('contact_pair', n)
        if restriction == 'mature':
            groups = [(20, 30)] if 100 <= n < 180 else []
            if 102 <= n < 180:
                groups += [(40, 50)]
            if 180 <= n < 350:
                groups = [(20, 50)]
        elif restriction == 'simultaneous' and 100 <= n < 105:
            groups = [(20, 23), (31, 31)]
        elif restriction == 'wide_history' and n == 101:
            groups = [(15, 26)]
        elif restriction == 'shrink' and n == 101:
            groups = [(20, 26)]
        elif restriction == 'boundary':
            groups = [(a - 19, b - 19) for a, b in groups]
        elif restriction == 'third_wide' and n == 105:
            groups += [(100, 120)]
        elif restriction == 'third_source' and n == 104:
            groups += [(42, 42)]
        elif restriction == 'late_join' and 105 <= n < 115:
            groups = [(20, 23), (27, 31)]
        elif restriction == 'far':
            groups = [(20, 23)] if 100 <= n < 105 else []
            if 103 <= n < 105:
                groups += [(60, 64)]
            if 105 <= n < 350:
                groups = [(19, 64)]
        f = sample(p, n, groups)
        if restriction == 'invalid' and n == 104:
            f = replace(f, valid_bits=b'\x00' * p.device.layout.bit_count)
        if restriction == 'unknown' and n == 104:
            p.contacts[0].has_unknown = True
        p.process(f, masked_contact=restriction == 'masked' and n == 104)
    assert not any(x['reason'] == 'immature_islands_coalesced' for x in p.summary()['candidate_decisions'])
    assert p.issues or any(c.problem or c.interrupted for c in p.contacts)
