"""Disconnected portions of one established optical footprint keep its identity."""
import pytest

from engine.modes.overground_running_processor import OvergroundRunningProcessor
from engine.overground_session import OvergroundSession
from hardware.sensor_frame import DeviceLayout
from hardware.walking_preflight import PreparedDevice
from tests.test_overground_running import frame, processor


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('wire_order', [None, (3, 1, 2)])
@pytest.mark.parametrize('edge_growth', [0, .0104])
def test_inner_split_of_established_stance_retains_events_and_side(reverse, wire_order, edge_growth):
    p = processor(3, starting_foot='Left')
    if wire_order is not None:
        layout = DeviceLayout.linear(3, wire_order=wire_order)
        p = OvergroundRunningProcessor(p.config, PreparedDevice(layout, 'running', -1, 0, 1000))
    for n in range(1100):
        bounds = []
        if 100 <= n < 300:
            bounds = [(.2, .38)]
        elif 450 <= n < 700:
            bounds = [(.85, 1.14)]
            if 560 <= n < 620:
                bounds = [(.85, .86), (.91, 1.14 + edge_growth)]
        elif 820 <= n < 980:
            bounds = [(1.6, 1.78)]
        if reverse:
            bounds = [(3-b, 3-a) for a,b in bounds]
        p.process(frame(p.device.layout, n, bounds))
    s = p.summary()
    assert not s['issues']
    assert len(p.contacts) == 3
    assert s['valid_steps'] == 2 and s['valid_cycles'] == 1
    assert [c.side for c in p.contacts] == ['left', 'right', 'left']
    assert p.contacts[1].start == 450 and p.contacts[1].end == 700
    assert s['contacts'][1]['contact_s']['valid']
    assert s['contacts'][1]['contact_s']['value'] == pytest.approx(.25)
    assert s['contacts'][1]['toe_m']['valid']
    report = p.build_report('manual')
    assert report.report_config_snapshot['algorithm'] == 'overground_running_v1.6'
    assert report.report_config_snapshot['tracking']['fragment_association'] == 'unique_existing_envelope_with_match_margin'


def test_merge_of_two_established_feet_still_breaks_identity():
    p = processor(starting_foot='Left')
    for n in range(500):
        bounds = [(.5, .63), (.79, .92)] if 100 <= n < 250 else []
        if 250 <= n < 350:
            bounds = [(.5, .92)]
        p.process(frame(p.device.layout, n, bounds))
    assert any(i['code'] == 'ambiguous_contacts' for i in p.issues)
    assert not p.summary()['valid_cycles']


def test_external_new_fragment_is_not_attached_to_previous_stance():
    p = processor()
    for n in range(500):
        bounds = [(.5, .63)] if 100 <= n < 300 else []
        if 180 <= n < 350:
            bounds += [(.68, .82)]
        p.process(frame(p.device.layout, n, bounds))
    assert len(p.contacts) == 2
    assert p.contacts[0].start == 100 and p.contacts[1].start == 180


def test_first_touch_islands_without_prior_envelope_remain_uncertain():
    p = processor(starting_foot='Left')
    lo, hi = p.positions[30], p.positions[36]
    for n in range(300):
        bounds = []
        if 100 <= n < 103:
            bounds = [(lo, lo), (hi, hi)]
        elif 103 <= n < 220:
            bounds = [(lo, hi)]
        p.process(frame(p.device.layout, n, bounds))
    assert any(i['code'] == 'ambiguous_contacts' for i in p.issues)
    assert not p.summary()['contacts'][-1]['touch_s']['valid']
    assert all(c.side == 'unknown' for c in p.contacts)


def test_formal_session_keeps_raw_islands_and_confirmed_contact(qtbot):
    p = processor(3, starting_foot='Left')
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    raw = []
    for n in range(900):
        bounds = []
        if 100 <= n < 250:
            bounds = [(.2, .38)]
        elif 400 <= n < 600:
            bounds = [(.85, 1.14)]
            if 480 <= n < 540:
                bounds = [(.85, .86), (.91, 1.15)]
        elif 720 <= n < 850:
            bounds = [(1.6, 1.78)]
        f = frame(p.device.layout, n, bounds)
        raw.append(f.contact_bits)
        session.on_frame(f)
    session.halt()
    report = session.build_report('manual')
    assert tuple(report.export_frames) == tuple(raw)
    assert not report.running_summary['issues']
    assert report.running_summary['valid_steps'] == 2
    assert report.running_summary['valid_cycles'] == 1
    assert len(session.processor.contacts) == 3
    assert session.processor.contacts[1].end == 600
