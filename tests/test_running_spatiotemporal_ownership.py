"""Declared optical trajectories, independent of association implementation."""
import pytest
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorSegment
from hardware.walking_preflight import PreparedDevice


def make(layout=None):
    return OvergroundRunningProcessor(OvergroundRunningConfig(min_contact_time=60, stop_type='Software command'),
        PreparedDevice(layout or DeviceLayout.linear(3), 'probe', -1, 0, 1000))


def feed(p, n, groups, reverse=False):
    bits = bytearray(p.device.layout.bit_count)
    for lo, hi in groups:
        if reverse:
            lo, hi = len(bits)-1-hi, len(bits)-1-lo
        bits[lo:hi+1] = b'\x01' * (hi-lo+1)
    p.process(SensorFrame('probe', p.device.layout, n, n, n+1, bytes(bits), b'\x01'*len(bits), b''))


@pytest.mark.parametrize('clear', [1, 2, 3])
@pytest.mark.parametrize('approach', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_nearby_feet_remain_independent(clear, approach, reverse):
    p = make()
    for n in range(750):
        groups = [(20, 35)] if 100 <= n < 650 else []
        if 200 <= n < 600:
            lo = max(36+clear, 70-max(0,n-300)//4) if approach else 36+clear
            groups.append((lo, lo+15))
        feed(p, n, groups, reverse)
    rows = p.summary()['contacts']
    assert [c['first_seen_sample'] for c in rows] == [100, 200]
    assert [c['touch_sample'] for c in rows] == [100, 200]
    assert [c['lift_sample'] for c in rows] == [650, 600]
    assert not p.issues


def test_external_island_cannot_be_absorbed_by_margin():
    p = make()
    for n in range(190):
        feed(p, n, [(20, 50)] if n >= 100 else [])
    assert p._associate_inner_fragments([(20,50),(52,53)]) == [(20,50),(52,53)]


@pytest.mark.parametrize('rolling', [False, True])
def test_known_split_retains_one_source(rolling):
    p = make()
    for n in range(600):
        groups = []
        if 100 <= n < 500:
            groups = ([(25,32),(48,55)] if rolling else [(20,27),(43,50)]) if 200 <= n < 300 else [(20,50)]
        feed(p,n,groups)
    assert [c.first_seen_sample for c in p.contacts] == [100]
    assert not p.issues
    assert p.summary()['contacts'][0]['touch_sample'] == 100


def test_mature_overlap_preserves_ids_earlier_touch_and_remote_span():
    p = make(DeviceLayout.linear(8))
    counts = None
    for n in range(700):
        groups = [(20,40),(60,80)] if 200 <= n < 550 else [(20,40)] if 100 <= n < 550 else []
        if 350 <= n < 450:
            groups = [(30,70)]
        if 300 <= n < 600:
            groups += [(150,170)]
        feed(p,n,groups)
        if n == 349:
            counts = [c.observed_samples for c in p.contacts[:2]]
        if n == 449:
            assert [c.observed_samples for c in p.contacts[:2]] == counts
    rows = p.summary()['contacts']
    assert [c['first_seen_sample'] for c in rows] == [100,200,300]
    assert [c['touch_sample'] for c in rows[:2]] == [100,200]
    assert all(not c[k]['valid'] for c in rows[:2] for k in ('lift_s','toe_m','contact_s'))
    assert rows[2]['touch_sample'] == 300 and rows[2]['lift_sample'] == 600
    assert rows[2]['contact_s']['value'] == pytest.approx(.3)
    assert p.epoch == 0


def test_private_tail_stays_unknown_until_actual_clear():
    p = make()
    for n in range(1200):
        groups = [(60,80)] if 100 <= n < 277 else []
        if 220 <= n < 277: groups += [(90,90)]
        if 277 <= n < 400: groups = [(60,90)]
        if 400 <= n < 500: groups = [(90,90)]
        for start,end,lo in [(450,650,150),(700,900,200),(950,1100,250)]:
            if start <= n < end: groups += [(lo,lo+20)]
        feed(p,n,groups)
    s = p.summary()
    assert s['contacts'][0]['touch_sample'] == 100
    assert not s['contacts'][0]['lift_s']['valid']
    cycle = next(c for c in s['cycles'] if c['duration_s']['value'] == .5)
    assert cycle['duration_s']['valid']
    assert not cycle['double_support_s']['valid']
    assert not cycle['single_support_s']['valid']
    assert not cycle['flight_s']['valid']
    assert not any(c['touch_sample'] == 400 for c in s['contacts'])


def test_overlap_takeover_cannot_create_retry_touch():
    p = make()
    for n in range(500):
        groups = [(20,40)] if 100 <= n < 200 else [(40,60)] if 200 <= n < 400 else []
        feed(p,n,groups)
    assert [c.first_seen_sample for c in p.contacts] == [100]
    row = p.summary()['contacts'][0]
    assert row['touch_sample'] == 100
    assert not row['toe_m']['valid'] and not row['lift_s']['valid']


def test_calibrated_seam_does_not_bridge_unobserved_gap():
    p = make(DeviceLayout((SensorSegment('1',0,0),SensorSegment('2',1,1.08))))
    bits = bytearray(192); bits[95:97] = b'\x01\x01'
    assert p._groups(bytes(bits)) == [(95,95),(96,96)]


@pytest.mark.parametrize('dark_length', [2, 4, 8])
def test_unknown_seam_cannot_prove_old_fragment_lift(dark_length):
    from tests.test_ground_local_observation import processor, sample, replay
    p = processor('run')
    frames = [sample(n, [(p.positions[87],p.positions[95])] if 100 <= n < 200 else
                     [(p.positions[98],p.positions[115])] if 200 <= n < 220 else [],
                     [1] if 198 <= n < 198+dark_length else []) for n in range(260)]
    replay(p,frames)
    row = p.summary()['contacts'][0]
    assert row['touch_sample'] == 100
    assert not row['lift_s']['valid'] and not row['contact_s']['valid']
    assert not any(c['touch_s']['valid'] for c in p.summary()['contacts'][1:])


@pytest.mark.parametrize('reverse', [False, True])
def test_known_bad_separator_only_extends_censored_occupancy(reverse):
    from dataclasses import replace
    p = make(DeviceLayout.linear(8))
    bad = len(p.positions)-1-95 if reverse else 95
    p = OvergroundRunningProcessor(p.config, replace(p.device,bad_indices=(bad,)))
    for n in range(500):
        bits = bytearray(len(p.positions))
        lo,hi = (80,93) if 100 <= n < 200 else (88,105) if 200 <= n < 400 else (0,-1)
        if hi >= lo:
            if reverse: lo,hi = len(bits)-1-hi,len(bits)-1-lo
            bits[lo:hi+1] = b'\x01'*(hi-lo+1)
        uncertain = bool(bits[bad])
        bits[bad] = 0
        p.process(SensorFrame('probe',p.device.layout,n,n,n+1,bytes(bits),b'\x01'*len(bits),b''),
                  masked_contact=uncertain)
    assert [c.first_seen_sample for c in p.contacts] == [100]
    row = p.summary()['contacts'][0]
    assert row['touch_sample'] == 100
    assert not row['toe_m']['valid'] and not row['lift_s']['valid'] and not row['contact_s']['valid']


def test_frozen_union_cannot_absorb_new_island_in_old_clear_area():
    p = make()
    for n in range(650):
        groups = [(20,40)] if 100 <= n < 200 else [(40,60)] if 200 <= n < 400 else []
        if 300 <= n < 500: groups += [(20,30)]
        feed(p,n,groups)
    rows = p.summary()['contacts']
    assert [c['first_seen_sample'] for c in rows] == [100,300]
    assert rows[0]['touch_sample'] == 100
    assert not rows[0]['contact_s']['valid']
    assert rows[1]['touch_sample'] == 300 and rows[1]['lift_sample'] == 500
    assert rows[1]['contact_s']['value'] == pytest.approx(.2)


@pytest.mark.parametrize('segments', [1,3,8,12])
@pytest.mark.parametrize('reverse', [False,True])
@pytest.mark.parametrize('clear', [1,2,3])
def test_production_filter_keeps_close_independent_sources(qtbot,segments,reverse,clear):
    from engine.overground_session import OvergroundSession
    from tests.test_running_pending_growth import sample
    p = make(DeviceLayout.linear(segments))
    session = OvergroundSession(p.config,type(p)); session.start_prepared(p.device)
    for n in range(750):
        groups = [(20,35)] if 100 <= n < 650 else []
        if 200 <= n < 600: groups += [(36+clear,51+clear)]
        session.on_frame(sample(p,n,groups,reverse))
    session.halt()
    rows = session.processor.summary()['contacts']
    assert [c['touch_sample'] for c in rows] == [100,200]
    assert [c['lift_sample'] for c in rows] == [650,600]
    assert all(c['contact_s']['valid'] for c in rows)
    assert not session.processor.issues


def test_model_recovery_without_estimated_edge_keeps_remote_span():
    from tests.test_ground_local_observation import processor, sample, replay
    p = processor('run')
    frames = []
    for n in range(310):
        ranges = [(p.positions[87],p.positions[95])] if 100 <= n < 200 else [(p.positions[98],p.positions[115])] if 200 <= n < 220 else []
        if 120 <= n < 270: ranges += [(p.positions[220],p.positions[240])]
        frames.append(sample(n,ranges,[1] if 198 <= n < 200 else []))
    _,observations = replay(p,frames)
    assert not observations[200].edges and observations[200].recovery_segments
    rows = p.summary()['contacts']
    old = next(c for c in rows if c['first_seen_sample']==100)
    remote = next(c for c in rows if c['first_seen_sample']==120)
    assert old['touch_sample']==100 and not old['lift_s']['valid'] and not old['contact_s']['valid']
    assert remote['touch_sample']==120 and remote['lift_sample']==270 and remote['contact_s']['valid']
    assert all(not c['touch_s']['valid'] for c in rows if c['first_seen_sample']>=198)


def test_split_without_inner_anchor_is_local_unknown_not_global_reset():
    p = make()
    for n in range(650):
        groups = [(20,50)] if 100 <= n < 500 else []
        if 200 <= n < 300: groups = [(15,25),(45,55)]
        if 180 <= n < 550: groups += [(150,170)]
        feed(p,n,groups)
    rows = p.summary()['contacts']
    assert [c['first_seen_sample'] for c in rows] == [100,180]
    assert p.epoch==0 and rows[0]['touch_sample']==100
    assert not rows[0]['toe_m']['valid'] and not rows[0]['contact_s']['valid']
    assert rows[1]['contact_s']['valid'] and rows[1]['lift_sample']==550


def test_private_join_with_visible_inner_fragment_does_not_duplicate_owner():
    p = make()
    for n in range(650):
        groups = [(20,60)] if 100 <= n < 500 else []
        if 200 <= n < 300: groups = [(20,30),(50,60)]
        if 280 <= n < 300: groups += [(65,65)]
        if 300 <= n < 400: groups = [(20,30),(50,65)]
        feed(p,n,groups)
    assert [c.first_seen_sample for c in p.contacts] == [100]
    assert p.summary()['contacts'][0]['touch_sample']==100
    assert not p.summary()['contacts'][0]['contact_s']['valid']
    assert p.epoch==0
