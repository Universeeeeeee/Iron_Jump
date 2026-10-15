"""Conditional optical ownership and publication, independent of metric coverage."""
from copy import deepcopy
import pytest
from tests.test_ground_candidate_groups import make, feed


def growing(n):
    if n == 100:
        return [(40, 41), (44, 45)]
    if 101 <= n < 110:
        return [(40, 46)]
    if 110 <= n < 120:
        return [(40, 50)]
    return [(40, 56)] if 120 <= n < 350 else []


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('anchor', [False, True])
def test_early_growth_recovers_with_or_without_other_foot(mode, anchor):
    p = make(mode)
    for n in range(400):
        feed(p, n, growing(n) + ([(200, 220)] if anchor and 20 <= n < 300 else []))
        if n == 159:
            events = [e for e in p.touch_events if e['touch_sample'] == 100]
            assert len(events) == 1 and events[0]['active']
            assert events[0]['published_sample'] == 159
    g = next(g for g in p._ownership_groups if g.get('recovery'))
    assert g['recovery']['rule_version'] == p.OWNERSHIP_RULE_VERSION
    assert g['recovery']['original_touch_sample'] == 100
    assert g['recovery']['valid_sample_intervals'] == [[100, 160]]
    assert g['recovery']['unique_samples'] == 60
    assert bool(g['recovery']['other_occupied_contacts']) == anchor
    assert sum(e['active'] for e in p.touch_events) == 1 + anchor
    assert len([e for e in p.event_audit if e['action'] == 'publish']) == 1 + anchor


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('kind', ['no_growth', 'two_wide_sources', 'long_separation', 'mature_overlap'])
def test_competing_or_insufficient_evidence_stays_unknown(mode, kind):
    p = make(mode)
    for n in range(500):
        if kind == 'no_growth':
            groups = [(40,43),(46,49)] if n == 100 else [(40,49)] if 101 <= n < 400 else []
        elif kind == 'two_wide_sources':
            groups = [(40,49),(52,61)] if n == 100 else [(40,61)] if 101 <= n < 400 else []
        elif kind == 'long_separation':
            groups = [(40,41),(44,45)] if 100 <= n < 200 else [(40,56)] if 200 <= n < 400 else []
        else:
            groups = ([(40,56)] if 100 <= n < 400 else []) + ([(65,81)] if 170 <= n < 400 else [])
            if 250 <= n < 400: groups = [(40,81)]
        feed(p, n, groups)
    assert not any(g.get('recovery') for g in p._ownership_groups)
    assert sum(e['active'] for e in p.touch_events) == (2 if kind == 'mature_overlap' else 0)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_reliable_count_does_not_wait_for_earlier_unknown_order(mode):
    p = make(mode)
    for n in range(350):
        groups = [(40,43),(46,49)] if n == 100 else [(40,49)] if 101 <= n < 300 else []
        if 150 <= n < 340: groups += [(200,220)]
        feed(p,n,groups)
        if n == 209:
            assert p.reliable_touch_count == 1
            c = next(c for c in p.contacts if round(c.start * (1000 if mode == 'walk' else 1)) == 150)
            assert not c.label
            assert p.touch_events[-1]['published_sample'] == 209
    assert p.reliable_touch_count == 1


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_recovered_event_order_uses_original_time_not_creation_id(mode):
    p = make(mode)
    for n in range(400):
        feed(p,n,growing(n) + ([(200,220)] if 120 <= n < 380 else []))
    active = [e for e in p.touch_events if e['active']]
    assert sorted(e['touch_sample'] for e in active) == [100,120]
    committed = [e for e in p.event_audit if e['action'] == 'sequence_commit']
    assert [e['touch_sample'] for e in committed] == [100,120]
    assert [e['label'] for e in committed] == ['A','B']


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_publication_is_idempotent_and_explicit_correction_is_auditable(mode):
    p = make(mode)
    for n in range(200): feed(p,n,[(40,60)] if n >= 100 else [])
    assert p.reliable_touch_count == 1
    audit = deepcopy(p.event_audit)
    p.summary(); p.summary(); p.build_report('manual'); p.build_report('manual')
    assert p.event_audit == audit
    c = p.contacts[0]
    c.candidate_outcome = 'associated_fragment'
    p._sync_touch_publications()
    assert p.reliable_touch_count == 0
    assert p.summary()['contacts'][0]['touch_sample'] is None
    correction = p.event_audit[-1]
    assert correction['action'] == 'retract' and correction['reason'] == 'associated_fragment'
    assert correction['event_id'] == audit[0]['event_id']
    assert correction['replaces_revision'] == audit[0]['revision']
    p._sync_touch_publications()
    assert p.event_audit[-1] == correction


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_later_local_ambiguity_does_not_retract_prior_touch(mode):
    p = make(mode)
    for n in range(500):
        groups = [(40,60)] if 100 <= n < 350 else []
        if 220 <= n < 250: groups += [(65,65)]
        if 250 <= n < 350: groups = [(40,65)]
        feed(p,n,groups)
    assert any(e['active'] and e['touch_sample'] == 100 for e in p.touch_events)
    assert not any(e['action'] == 'retract' for e in p.event_audit)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_missing_observation_cannot_supply_recovery_votes(mode):
    from dataclasses import replace
    p = make(mode)
    p = type(p)(p.config, replace(p.device, bad_indices=(48,)))
    for n in range(400): feed(p,n,growing(n))
    assert not any(g.get('recovery') for g in p._ownership_groups)
    assert p.reliable_touch_count == 0


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_frame_gap_before_confirmation_cannot_be_recovered(mode):
    p = make(mode)
    for n in range(400):
        if n == 140: continue
        feed(p,n,growing(n))
    assert not any(g.get('recovery') for g in p._ownership_groups)
    assert p.reliable_touch_count == 0


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_recovered_owner_uses_union_once_and_report_keeps_audit(mode):
    from data.subject_store import _report_detail, _report_from_detail
    p = make(mode)
    for n in range(400): feed(p,n,growing(n))
    g = next(g for g in p._ownership_groups if g.get('recovery'))
    c = p.contacts[g['recovery']['owner_id']]
    assert c.observed_samples == g['observed_samples'] == 250
    assert c.valid_sample_intervals == [[100,350]]
    report = p.build_report('manual')
    saved = _report_from_detail(_report_detail(report))
    key = 'walking_summary' if mode == 'walk' else 'running_summary'
    s = getattr(saved,key)
    assert s['event_audit'] == p.event_audit
    assert s['event_publications'] == p.touch_events
    assert s['ownership_recoveries'] == [g['recovery']]
    assert report.touch_count == saved.touch_count == 1


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_session_counter_publishes_reliable_touch_before_sequence(qtbot, mode):
    from engine.overground_session import OvergroundSession
    from hardware.sensor_frame import SensorFrame
    p = make(mode)
    session = OvergroundSession(p.config,type(p)); session.start_prepared(p.device)
    snapshots=[]; session.snapshot.connect(snapshots.append)
    for n in range(260):
        groups = [(40,43),(46,49)] if n == 100 else [(40,49)] if 101 <= n else []
        if 150 <= n: groups += [(200,220)]
        bits=bytearray(len(p.positions))
        for low,high in groups: bits[low:high+1]=b'\x01'*(high-low+1)
        session.on_frame(SensorFrame(p.device.stream_id,p.device.layout,n,n,n+1,
                                    bytes(bits),b'\x01'*len(bits),b''))
    session.publish_snapshot()
    assert snapshots[-1]['touch_count'] == 1
    assert session.processor.reliable_touch_count == 1
    assert not next(c for c in session.processor.contacts if session.processor._event_sample(c)==150).label
    session.halt()
    assert session.processor.reliable_touch_count == 1


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_recovered_contact_correction_is_not_undone_by_next_sample(mode):
    p = make(mode)
    for n in range(200): feed(p,n,growing(n))
    g = next(g for g in p._ownership_groups if g.get('recovery'))
    c = p.contacts[g['recovery']['owner_id']]
    c.candidate_outcome = 'associated_fragment'
    for n in range(200,400): feed(p,n,growing(n))
    assert p.reliable_touch_count == 0
    assert len([e for e in p.event_audit if e['action']=='retract']) == 1


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_closed_private_unknown_cannot_be_skipped_as_nonstep(mode):
    p = make(mode)
    for n in range(550):
        groups = [(200,220)] if 20 <= n < 90 else []
        if n == 100: groups += [(40,41),(44,45)]
        if 101 <= n < 200: groups += [(40,46)]
        if 250 <= n < 400: groups += [(260,280)]
        feed(p,n,groups)
    assert p.reliable_touch_count == 2
    s=p.summary()
    assert s['valid_steps'] == 0 and s['valid_cycles'] == 0


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_source_shrink_is_competing_shape_evidence(mode):
    p = make(mode)
    for n in range(400):
        groups = [(40,47)] if n == 100 else [(40,41)] if 101 <= n < 110 else []
        if 108 <= n < 110: groups += [(44,45)]
        if 110 <= n < 120: groups = [(40,46)]
        if 120 <= n < 350: groups = [(40,60)]
        feed(p,n,groups)
    assert not any(g.get('recovery') for g in p._ownership_groups)
    assert p.reliable_touch_count == 0


def test_recovered_merged_group_does_not_leave_archived_order_barrier():
    p = make('run')
    for n in range(350):
        groups = [(40,41),(44,45)] if n==100 else [(40,46)] if 101<=n<300 else []
        if n==110: groups += [(55,56),(59,60)]
        if 111<=n<120: groups += [(55,61)]
        if 120<=n<300: groups = [(40,61)]
        feed(p,n,groups)
    g=p._ownership_groups[0]
    assert g['recovery']['unique_samples']==60
    assert g['observed_samples']==200 and g['valid_sample_intervals']==[[100,300]]
    assert len(g['recovery']['source_ids'])==4
    assert p._ownership_groups[1]['state']=='merged'
    assert p._ownership_barriers()==[]
    assert p.reliable_touch_count==1


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_retraction_recommits_later_sequence_without_republishing_touch(mode):
    p=make(mode)
    for n in range(600):
        groups=[]
        for start, low in [(100,40),(250,100),(400,160)]:
            if start <= n < start+80: groups.append((low,low+20))
        feed(p,n,groups)
    assert [c.label for c in p.contacts]==['A','B','A']
    ids={e['contact_id']:e['event_id'] for e in p.touch_events}
    p.contacts[1].candidate_outcome='associated_fragment'
    feed(p,600,[])
    assert p.reliable_touch_count==2
    assert [c.label for c in p.contacts]==['A','','B']
    assert {e['contact_id']:e['event_id'] for e in p.touch_events}==ids
    assert len([e for e in p.event_audit if e['action']=='publish'])==3
    assert len([e for e in p.event_audit if e['action']=='retract'])==1
    assert len([e for e in p.event_audit if e['action']=='sequence_retracted'])==2
    assert p.event_audit[-1]['action']=='sequence_commit'
    assert p.event_audit[-1]['event_id']==ids[2] and p.event_audit[-1]['label']=='B'
    assert p.summary()['valid_steps']==1


def test_publication_retains_estimated_original_time_and_bounds():
    p=make('walk')
    for n in range(159): feed(p,n,[(40,60)] if n>=100 else [])
    # A bounded local observation can put the estimated edge between samples.
    c=p.contacts[0];c.start=.1005;c.edge_estimates['touch']=[100,101]
    feed(p,159,[(40,60)]);feed(p,160,[(40,60)])
    event=p.touch_events[0]
    assert event['touch_sample']==pytest.approx(100.5)
    assert event['touch_bounds']==[100,101]
    assert p.summary()['contacts'][0]['touch_sample'] is None  # still an estimate
