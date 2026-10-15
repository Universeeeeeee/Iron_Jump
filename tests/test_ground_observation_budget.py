"""Final unknown attribution releases ordering, never publication or relationships."""
from copy import deepcopy
import pytest
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import masked_frame, uncertain_contact
from tests.test_ground_candidate_groups import make
from tests.test_ground_ownership_publication import growing
from tests.test_running_pending_growth import sample


def replay(mode, filtered, kind, reverse=False, late_growth=False, reappear=False,
           first_remote=2300, growth_at=2200, late_join=False, join_at=2200, renewed_group=False,
           followups=True, healthy_anchor=False):
    p = make(mode)
    p.config.starting_foot = 'Left'
    p.config.stop_threshold_s = 10
    optical = GroundStabilityFilter(p.device.layout, p.device.bad_indices) if filtered else None
    snapshots = {}
    def consume(frame):
        p.process(frame, masked_contact=uncertain_contact(frame, p.device.bad_indices))
        if frame.sample_index in {2129,2130,2169,2170,2359,2505,2900,3103,3111,3259,3459,3659,first_remote+59}:
            snapshots[frame.sample_index] = deepcopy(p)
    for n in range(3700):
        if kind == 'group':
            groups = [(40,43),(46,49)] if n == 100 else [(40,49)] if 101 <= n < 3100 else []
        else:
            groups = growing(n)
            if int(kind) <= n < 3100:
                groups += [(30 if late_growth and n >= growth_at else 38,38)]
            if late_join and join_at <= n < 3100:
                groups += [(40,56)] if n < join_at+50 else []
                if n >= join_at+50:
                    groups = [(38,56)]
            if renewed_group:
                groups += growing(n-1950)
        for first,low in [(first_remote,200),*([(2500,260),(2700,320)] if followups else [])]:
            if first <= n < first+120:
                groups += [(low,low+16)]
        if reappear and 3200 <= n < 3320:
            groups += [(30,38)]
        if healthy_anchor and 20<=n<3100:
            groups += [(5,25)]
        if reverse:
            groups = [(600-high,600-low) for low,high in groups]
        frame = sample(p,n,groups)
        for measured in optical.feed(masked_frame(frame,p.device.bad_indices)) if optical else [frame]:
            consume(measured)
    if optical:
        for measured in optical.flush():
            consume(measured)
    return p,snapshots


def event_contact(p, first):
    return next(c for c in p.contacts if p._event_sample(c) == first)


@pytest.mark.parametrize('mode',['walk','run'])
@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('kind',['130','170','group'])
@pytest.mark.parametrize('reverse',[False,True])
def test_budget_finalizes_wait_but_preserves_occupancy_and_gap(mode,filtered,kind,reverse):
    p,states = replay(mode,filtered,kind,reverse)
    first = 100 if kind == 'group' else int(kind)
    deadline = first+2000
    at_publish = states[2359]
    remote = event_contact(at_publish,2300)
    assert at_publish._touch_events[remote.id]['published_sample'] == 2359
    assert remote.id in at_publish._committed_contacts
    assert remote.label == 'A' and remote.side == 'unknown'
    if kind != 'group':
        before = states[deadline-1]
        if mode == 'run' and kind == '170':
            assert before._narrow_candidates[0].get('observation_closed_sample') is None
            q = states[deadline]._narrow_candidates[0]
            assert q['observation_wait_since'] == first
            assert q['observation_closed_sample'] == deadline
        else:
            c = event_contact(states[deadline],first)
            if mode == 'run':
                assert c.ownership_competition[0]['outcome'] == 'unresolved'
                assert c.ownership_competition[0]['decided_sample'] == deadline
            else:
                assert c.candidate_outcome == 'unresolved'
                assert c.observation_wait_since == first
                assert c.observation_closed_sample == deadline
            assert c in states[deadline].active and c.end is None
    else:
        g = states[2130]._ownership_groups[0]
        assert g['closed_sample'] == 2100 and g['tracking_ended_sample'] is None
    assert not any(e['active'] and e['touch_sample'] == first for e in p.touch_events)
    assert [e['touch_sample'] for e in p.event_audit if e['action']=='sequence_commit'] == ([2300,2500,2700] if kind=='group' else [100,2300,2500,2700])
    # Event ordering can advance while support remains unknown during the occupancy.
    summary = states[2900].summary()
    if mode == 'run':
        crossing = next(s for s in summary['steps'] if p._event_sample(p.contacts[s['to_id']]) == 2300)
        assert not crossing['time_s']['valid']
        remote_steps = [s for s in summary['steps'] if p._event_sample(p.contacts[s['from_id']]) >= 2300]
        assert all(s['time_s']['valid'] for s in remote_steps)
        assert all(not c['single_support_s']['valid'] for c in summary['cycles'])
    else:
        assert all(p._event_sample(p.contacts[s['from_id']]) >= 2300 for s in summary['steps'])
        assert summary['valid_steps'] == 2
        assert summary['valid_support_cycles'] == 0
    previous = deepcopy((p.touch_events,p.event_audit,p._candidate_decisions))
    p.summary();p.summary();p.build_report('manual');p.build_report('manual')
    assert previous == (p.touch_events,p.event_audit,p._candidate_decisions)


@pytest.mark.parametrize('mode',['walk','run'])
@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('kind',['130','170'])
def test_final_unknown_late_growth_does_not_reopen_original_touch(mode,filtered,kind):
    p,states = replay(mode,filtered,kind,late_growth=True,reappear=True)
    assert not any(e['active'] and e['touch_sample']==int(kind) for e in p.touch_events)
    assert len([e for e in p.touch_events if e['active'] and e['touch_sample']==3200]) == 1
    assert event_contact(states[2359],2300).label == 'A'
    assert sum(e['action']=='publish' and e['touch_sample']==3200 for e in p.event_audit) == 1


@pytest.mark.parametrize('mode,kind',[('run','130'),('run','170'),('walk','130')])
@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('when',['before','at'])
def test_already_published_touch_commits_at_budget_boundary(mode,kind,filtered,when):
    deadline = int(kind)+2000
    first = 2000 if when=='before' else deadline-59
    p,states = replay(mode,filtered,kind,first_remote=first)
    event = next(e for e in p.touch_events if e['touch_sample']==first)
    assert event['published_sample']==first+59
    commit = next(e for e in p.event_audit if e['action']=='sequence_commit' and e['touch_sample']==first)
    assert commit['sample']==deadline
    if when=='before':
        assert not event_contact(states[first+59],first).label
    assert event_contact(states[deadline],first).label=='A'


@pytest.mark.parametrize('mode,kind',[('run','130'),('run','170'),('walk','130')])
@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('join_at',[1800,2200])
def test_joining_source_cannot_restart_budget_or_publish(mode,kind,filtered,join_at):
    p,states = replay(mode,filtered,kind,late_join=True,join_at=join_at)
    assert not any(e['active'] and e['touch_sample']==int(kind) for e in p.touch_events)
    assert event_contact(states[2359],2300).id in states[2359]._committed_contacts
    closed = [g for g in p._ownership_groups if any(s['first_sample']==int(kind) for s in g['sources'])]
    assert closed and all(g['state']=='closed_unknown' and g['close_reason']=='observation_budget' for g in closed)
    assert all(g['observation_wait_since']==int(kind) for g in closed)
    assert all(g['unresolved_since_sample']==join_at+50 for g in closed)
    assert all(g['closed_sample']==max(int(kind)+2000,join_at+50) for g in closed)


@pytest.mark.parametrize('filtered',[False,True])
def test_new_competition_uses_first_unresolved_budget(filtered):
    p,states = replay('run',filtered,'130',renewed_group=True)
    c = event_contact(states[2130],130)
    assert len(c.ownership_competition)>=2
    assert min(r['detected_sample'] for r in c.ownership_competition)==130
    assert all(r['outcome']=='unresolved' and r['decided_sample']==2130 for r in c.ownership_competition)


@pytest.mark.parametrize('mode',['walk','run'])
@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('kind',['130','170'])
def test_independent_growth_before_deadline_preserves_original_touch(mode,filtered,kind):
    p,states = replay(mode,filtered,kind,late_growth=True,growth_at=2100)
    events = [e for e in p.touch_events if e['active'] and e['touch_sample']==int(kind)]
    assert len(events)==1 and events[0]['published_sample']==2100
    c = event_contact(states[2359],int(kind))
    assert getattr(c,'observation_closed_sample',None) is None


@pytest.mark.parametrize('mode,kind',[('run','130'),('run','170'),('walk','130')])
@pytest.mark.parametrize('filtered',[False,True])
def test_final_unknown_gap_survives_clear_before_next_touch(mode,kind,filtered):
    p,states = replay(mode,filtered,kind,first_remote=3200,followups=False)
    c = event_contact(states[3259],3200)
    assert c.label=='A' and c.side=='unknown'
    assert c.id in states[3259]._committed_contacts
    assert sum(e['action']=='sequence_commit' and e['touch_sample']==3200 for e in p.event_audit)==1
    summary = p.summary()
    assert summary['valid_steps']==0 and summary['valid_cycles']==0


@pytest.mark.parametrize('filtered',[False,True])
def test_known_first_foot_is_not_inherited_across_timed_out_contact(filtered):
    p=make('walk');p.config.starting_foot='Left';p.config.stop_threshold_s=10
    optical=GroundStabilityFilter(p.device.layout,p.device.bad_indices) if filtered else None
    for n in range(2500):
        groups=[(40,60)] if 20<=n<350 else []
        if 130<=n:groups += [(100,100)]
        if 2300<=n<2420:groups += [(200,216)]
        f=sample(p,n,groups)
        for measured in optical.feed(masked_frame(f,p.device.bad_indices)) if optical else [f]:
            p.process(measured)
            if measured.sample_index==79:
                assert event_contact(p,20).side=='left'
            if measured.sample_index==2129:
                assert p._identity_known
            if measured.sample_index==2359:
                assert event_contact(p,20).side=='left'
                assert event_contact(p,2300).side=='unknown'
                assert event_contact(p,2300).label=='A'


@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('kind',['130','170'])
def test_pre_gap_mature_contact_cannot_compete_with_new_local_a_label(filtered,kind):
    p,states=replay('run',filtered,kind,healthy_anchor=True)
    before=states[2129]
    anchor=event_contact(before,20)
    assert anchor.label=='A' and anchor.side=='left' and anchor in before.active
    current=states[2359]
    remote=event_contact(current,2300)
    assert remote.label=='A' and remote.side=='unknown' and remote.problem is None
    assert remote.id in current._committed_contacts
    assert event_contact(current,20) in current.active
