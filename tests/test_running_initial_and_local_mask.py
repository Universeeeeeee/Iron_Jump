"""Initial asynchronous optical islands and isolated bad-beam boundaries."""
from dataclasses import replace
import pytest
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from engine.overground_session import OvergroundSession
from hardware.sensor_frame import DeviceLayout
from hardware.walking_preflight import PreparedDevice
from hardware.beam_quality import masked_frame
from tests.test_overground_running import frame,processor


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('segments,wire_order', [(1, None), (3, None), (8, None), (12, None), (3, (3, 1, 2))])
@pytest.mark.parametrize('minimum', [20, 60])
def test_first_asynchronous_short_islands_preserve_first_observed_touch(qtbot,reverse,filtered,segments,wire_order,minimum):
    p=processor(segments,starting_foot='Left',min_contact_time=minimum)
    if wire_order is not None:
        layout=DeviceLayout.linear(segments,wire_order=wire_order)
        p=OvergroundRunningProcessor(p.config,PreparedDevice(layout,'running',-1,0,1000))
    session=OvergroundSession(p.config,type(p)) if filtered else None
    if session:session.start_prepared(p.device)
    for n in range(700):
        bounds=[]
        if n==100:bounds=[(.23,.24)]
        if n==101:bounds=[(.22,.24)]
        if n==102:bounds=[(.22,.25),(.30,.31)]
        if 103<=n<350:bounds=[(.21,.38)]
        if 420<=n<600:bounds=[(.64,.8)]
        if reverse:bounds=[(segments-b,segments-a) for a,b in bounds]
        f=frame(p.device.layout,n,bounds)
        if session:session.on_frame(f)
        else:p.process(f)
    if session:session.halt();p=session.processor
    assert len([c for c in p.contacts if c.candidate_outcome!='associated_fragment'])==2 and not p.issues
    assert p.contacts[0].start==100 and p.contacts[0].end==350
    assert p.contacts[0].confirmed
    assert not p.summary()['contacts'][0]['touch_s']['valid']
    assert p.summary()['contacts'][0]['first_seen_sample']==100
    assert not p.summary()['contacts'][0]['toe_m']['valid']
    assert p.contacts[0].side=='unknown' and p.contacts[1].side=='unknown'
    assert not p.summary()['steps'][0]['time_s']['valid']
    assert p.summary()['duration_s'] is None


@pytest.mark.parametrize('kind',['wide','simultaneous','late','confirmed'])
def test_first_fragment_merge_does_not_absorb_genuine_foot_ambiguity(kind):
    p=processor(3,min_contact_time=60)
    for n in range(500):
        bounds=[]
        if 100<=n<250:bounds=[(.2,.22)]
        second=100 if kind=='simultaneous' else (170 if kind=='confirmed' else 102)
        join=200 if kind=='confirmed' else (115 if kind=='late' else 103)
        if second<=n<join:bounds +=[(.30,.34)] if kind=='confirmed' else[(.30,.31)]
        if kind=='wide' and 100<=n<join:bounds=[(.2,.25)] + ([(.3,.31)] if n>=102 else[])
        if join<=n<350:bounds=[(.2,.4)]
        p.process(frame(p.device.layout,n,bounds))
    assert any(i['code']=='ambiguous_contacts' for i in p.issues)


@pytest.mark.parametrize('code',['ambiguous_contacts','masked_contact_boundary','frame_gap'])
def test_unconfirmed_interruption_reason_is_not_mislabeled_short_contact(code):
    p=processor(3,min_contact_time=60)
    for n in range(110):
        p.process(frame(p.device.layout,n,[(.2,.35)] if n>=100 else[]))
    p.break_continuity(code,110)
    p.process(frame(p.device.layout,110,[(.8,.95)]))
    rows=p.summary()['contacts']
    assert rows[0]['touch_s']['missing_reason']==code
    assert rows[0]['contact_s']['missing_reason']==code
    assert p.summary()['steps'][0]['time_s']['missing_reason']==code


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('wire_order', [None, (8, 2, 6, 1, 4, 3, 5, 7)])
def test_local_mask_keeps_foreign_healthy_touch_and_never_creates_recovered_bad_foot(qtbot,reverse,wire_order):
    layout=DeviceLayout.linear(8,wire_order=wire_order)
    target=6.0 if not reverse else 1.988
    bad=min(range(layout.bit_count),key=lambda i: abs(layout.positions_m[i]-target))
    device=PreparedDevice(layout,'running',-1,0,3000,bad_indices=(bad,))
    p=OvergroundRunningProcessor(processor(8,starting_foot='Left',min_contact_time=60).config,device)
    session=OvergroundSession(p.config,type(p));session.start_prepared(device)
    for n in range(1200):
        bounds=[]
        if 100<=n<400:bounds=[(.2,.4)]
        if 500<=n<900:bounds=[(6.0832,6.25)]
        if 520<=n<700:bounds=[(6.0104,6.25)]
        if 600<=n<1000:bounds +=[(7.2,7.4)]
        if reverse:bounds=[(7.988-b,7.988-a) for a,b in bounds]
        f=frame(layout,n,bounds);bits=bytearray(f.contact_bits);bits[bad]=1;f=replace(f,contact_bits=bytes(bits))
        session.on_frame(masked_frame(f,(bad,)),raw_frame=f)
    session.halt();p=session.processor
    assert len(p.contacts)==3
    good=p.contacts[-1]
    assert good.start==600 and good.end==1000 and good.confirmed
    assert p.summary()['contacts'][-1]['contact_s']['valid']
    affected=p.contacts[1]
    assert affected.interrupted=='masked_contact_boundary' and affected.end is None
    assert good.side=='unknown'
    assert session.build_report('manual').export_frames[600][bad]==1


@pytest.mark.parametrize('reverse', [False, True])
def test_local_mask_preserves_remote_pending_original_onset(reverse):
    layout = DeviceLayout.linear(8)
    bad = 576 if not reverse else 191
    device = PreparedDevice(layout, 'running', -1, 0, 3000, bad_indices=(bad,))
    p = OvergroundRunningProcessor(processor(8, min_contact_time=60).config, device)
    for n in range(1000):
        bounds = []
        if 100 <= n < 400:
            bounds = [(.2, .4)]
        if 500 <= n < 850:
            bounds = [(6.0832, 6.25)]
        if 580 <= n < 700:
            bounds = [(6.0104, 6.25)]
        if 570 <= n < 590:
            bounds += [(7.2, 7.22)]
        if 590 <= n < 900:
            bounds += [(7.2, 7.4)]
        if reverse:
            bounds = [(7.988-b, 7.988-a) for a, b in bounds]
        p.process(frame(layout, n, bounds), masked_contact=580 <= n < 700)
    assert len(p.contacts) == 3
    good = p.contacts[-1]
    assert good.start == 570 and good.end == 900 and good.confirmed
    assert p.summary()['contacts'][-1]['contact_s']['valid']
    assert good.side == 'unknown'


def test_mask_after_confirmation_preserves_pre_mask_touch_interval():
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout, 'running', -1, 0, 3000, bad_indices=(576,))
    p = OvergroundRunningProcessor(processor(8, min_contact_time=60).config, device)
    for n in range(1000):
        bounds = []
        if 100 <= n < 400:
            bounds = [(5.1, 5.3)]
        if 500 <= n < 850:
            bounds = [(6.0832, 6.25)]
        if 580 <= n < 700:
            bounds = [(6.0104, 6.25)]
        p.process(frame(layout, n, bounds), masked_contact=580 <= n < 700)
    s = p.summary()
    assert s['steps'][0]['time_s']['value'] == pytest.approx(.4)
    assert s['steps'][0]['time_s']['valid']
    assert s['contacts'][1]['touch_s']['valid']
    assert s['contacts'][1]['contact_s']['missing_reason'] == 'masked_contact_boundary'
    assert not s['contacts'][1]['toe_m']['valid']


def test_masked_narrow_new_island_cannot_lose_bad_boundary_at_promotion():
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout, 'running', -1, 0, 3000, bad_indices=(576,))
    p = OvergroundRunningProcessor(processor(8, min_contact_time=60).config, device)
    for n in range(1000):
        bounds = [(5.1, 5.3)] if 100 <= n < 700 else []
        if 300 <= n < 310:
            bounds += [(6.0104, 6.0208)]
        if 310 <= n < 800:
            bounds += [(6.0208 + .0208 * min((n - 310) // 10, 3), 6.25)]
        p.process(frame(layout, n, bounds), masked_contact=300 <= n < 310)
    assert len(p.contacts) == 2
    assert p.contacts[1].start == 300
    assert p.contacts[1].interrupted == 'masked_contact_boundary'
    assert not p.summary()['contacts'][1]['touch_s']['valid']
    assert p.contacts[1].end is None
