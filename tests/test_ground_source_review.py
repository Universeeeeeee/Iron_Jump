"""B: append source decisions without relaxing initial-growth or long islands."""
from copy import deepcopy
from dataclasses import replace
import pytest
from tests.test_ground_candidate_groups import make, feed, field_replay


def source_decisions(p):
    return [d for g in p._ownership_groups for d in g.get('source_decisions',[]) if d['outcome']=='associated']


def sequence(mode, recovered=False, long_source=False, damage=None, minimum=60, joined=305, reverse=False):
    p=make(mode);p.config=replace(p.config,min_contact_time=minimum,stop_threshold_s=10)
    first=None;events=None
    for n in range(650):
        groups=[]
        if 100<=n<600:
            groups=[(40,60 if n<303 else 61 if n<joined else 63)]
            if recovered and n<110:
                groups=[(40,41),(44,45)] if n==100 else [(40,46)]
        if 300<=n<joined:groups += [(63,63)]
        if long_source and 400<=n<560:groups += [(66,66)]
        if long_source and 560<=n<600:groups=[(40,66)]
        if damage=='gap' and n==302:groups=[(40,61)]
        if damage=='far' and 300<=n<305:groups=[(40,60),(70,70)]
        if damage=='far' and 305<=n<600:groups=[(40,70)]
        if damage=='wide' and 300<=n<305:groups=[(40,60),(63,72)]
        if damage=='wide' and 305<=n<600:groups=[(40,72)]
        if reverse:groups=sorted((220-hi,220-lo) for lo,hi in groups)
        feed(p,n,groups)
        if n==200:
            first=deepcopy([g.get('recovery') for g in p._ownership_groups]);events=deepcopy(p.touch_events)
    return p,first,events


@pytest.mark.parametrize('mode',['walk','run'])
@pytest.mark.parametrize('minimum',[20,60])
@pytest.mark.parametrize('recovered',[False,True])
def test_short_source_review_preserves_original_event_and_first_recovery(mode,minimum,recovered):
    p,first,events=sequence(mode,recovered,minimum=minimum)
    accepted=source_decisions(p)
    assert len(accepted)==1
    d=accepted[0]
    assert d['evidence_start_sample']==300 and d['decided_sample']>=314
    assert d['owner_id']==events[0]['contact_id'] and d['rule_version']
    assert p.touch_events==events
    if recovered:assert [g.get('recovery') for g in p._ownership_groups]==first
    assert not p._ownership_barriers()
    g=p._ownership_groups[0]
    assert g['observed_samples']==sum(b-a for a,b in g['valid_sample_intervals'])
    assert p.summary()['valid_contact_durations']==1


@pytest.mark.parametrize('mode',['walk','run'])
def test_short_approval_does_not_absorb_later_long_source(mode):
    p,first,events=sequence(mode,True,True)
    assert len(source_decisions(p))==1
    assert [g.get('recovery') for g in p._ownership_groups]==first
    assert any(a==400 for a,b,e in p._ownership_barriers())
    assert p.touch_events==events
    assert p.summary()['valid_contact_durations']==0


@pytest.mark.parametrize('mode',['walk','run'])
@pytest.mark.parametrize('damage',['gap','far','wide'])
def test_observed_competition_and_discontinuity_reject_short_source(mode,damage):
    p,_,events=sequence(mode,True,damage=damage)
    assert not source_decisions(p)
    assert p.touch_events==events
    assert p.summary()['valid_contact_durations']==0


@pytest.mark.parametrize('field_replay',['walk'],indirect=True)
def test_field_short_sources_are_individual_and_masked_contact_remains_unknown(field_replay):
    _,p,_=field_replay
    accepted=source_decisions(p)
    starts={d['evidence_start_sample'] for d in accepted}
    assert {43009,47085,47117,42373,45740,49264} <= starts
    assert 45564 not in starts
    row=next(r for r in p.summary()['contacts'] if r['touch_sample']==47722)
    assert row['lift_sample']==48621 and not row['contact_s']['valid']
    assert any(a==45564 for a,b,e in p._ownership_barriers())


@pytest.mark.parametrize('field_replay',['run'],indirect=True)
def test_field_103600_stays_unresolved(field_replay):
    _,p,_=field_replay
    assert not any(d['evidence_start_sample']==103600 for d in source_decisions(p))
    assert any(a==103600 for a,b,e in p._ownership_barriers())


@pytest.mark.parametrize('mode',['walk','run'])
def test_two_independently_published_feet_never_enter_single_owner_review(mode):
    p=make(mode);p.config=replace(p.config,min_contact_time=60,stop_threshold_s=10)
    ledger=None
    for n in range(450):
        groups=([(40,60)] if 100<=n<400 else []) + ([(65,85)] if 200<=n<300 else [])
        if 300<=n<400:groups=[(40,85)]
        feed(p,n,groups)
        if n==299:ledger=deepcopy(p.touch_events)
    assert len(ledger)==2 and p.touch_events==ledger
    assert not source_decisions(p)
    assert all(not g.get('recovery') and not g.get('established_owner') for g in p._ownership_groups)
    assert any(e['reason']=='independent_mature_source' for g in p._ownership_groups for e in g['recovery_evaluations'])
    assert p.summary()['valid_contact_durations']==0


@pytest.mark.parametrize('mode',['walk','run'])
@pytest.mark.parametrize('damage',['mature','published_later','competing_owner','interrupted',
    'missing_prejoin','unreliable_prejoin','third_projection','opposite_direction',
    'unreliable_postjoin','split_postjoin','missing_postjoin','joint_does_not_cover_source'])
def test_each_required_evidence_blocks_review_when_missing(mode,damage):
    from engine.ground_source_review import review_source,ownership_record
    p,_,_=sequence(mode,True)
    g=deepcopy(p._ownership_groups[0]);s=next(s for s in g['sources'] if s['first_sample']==300)
    record=ownership_record(g)
    if damage=='mature':s['evidence_at_join']['confirmed']=True
    elif damage=='published_later':
        s['contact_id']=999;p._touch_events[999]={'active':True}
    elif damage=='competing_owner':g['competing_owner_ids']=[999]
    elif damage=='interrupted':s['evidence_at_join']['interrupted']='frame_gap'
    elif damage=='missing_prejoin':s['review_observations'].pop(1)
    elif damage=='unreliable_prejoin':s['review_observations'][0][1][0][2]=False
    elif damage=='third_projection':s['review_observations'][0][1].append([65,65,True,[]])
    elif damage=='opposite_direction':p.direction=-1
    else:
        run=next(r for r in g['observation_runs'] if r[0]==305)
        if damage=='unreliable_postjoin':run[3]=False
        elif damage=='split_postjoin':run[2]=[[40,61],[63,63]]
        elif damage=='missing_postjoin':run[0]=306
        elif damage=='joint_does_not_cover_source':run[2]=[[40,62]]
    reason,_=review_source(p,g,s,record)
    assert reason is not None


@pytest.mark.parametrize('mode',['walk','run'])
def test_pending_and_metric_barriers_follow_each_source_not_first_recovery_set(mode):
    from engine.ground_source_review import assigned_sources
    from engine.ground_metric_evidence import group_release_evidence
    p,first,_=sequence(mode,True,True)
    g=p._ownership_groups[0]
    assert [g.get('recovery')]==first
    assert len(assigned_sources(g))==len(g['recovery']['source_ids'])+1
    long=next(s for s in g['sources'] if s['first_sample']==400)
    assert long['source_id'] not in assigned_sources(g)
    evidence=group_release_evidence(p._ownership_groups,g['recovery']['owner_id'])
    assert not evidence['occupancy_valid'] and evidence['missing_reason']=='competing_source'
    # Reopen only the observation state to exercise the live ordering predicate.
    g['state']='observing'
    c=deepcopy(p.contacts[g['recovery']['owner_id']]);c.start=.45 if mode=='walk' else 450
    assert p._pending_group_before(c)
    c.start=.35 if mode=='walk' else 350
    assert not p._pending_group_before(c)
    assert g['unresolved_since_sample']==g['recovery']['budget_start_sample']


@pytest.mark.parametrize('mode',['walk','run'])
def test_merging_two_attributed_owners_retains_decisions_and_competition(mode):
    from engine.ground_metric_evidence import group_release_evidence
    from engine.ground_source_review import ownership_record
    p=make(mode);p.config=replace(p.config,min_contact_time=60,stop_threshold_s=10)
    first=None;events=None
    for n in range(500):
        groups=[]
        if n==100:groups=[(40,41),(44,45)]
        elif 100<n<110:groups=[(40,46)]
        elif 110<=n<450:groups=[(40,60 if n<303 else 61 if n<305 else 63)]
        if 200<=n<450:groups += [(100,120 if n<323 else 121 if n<325 else 123)]
        if 300<=n<305:groups += [(63,63)]
        if 320<=n<325:groups += [(123,123)]
        if 400<=n<450:groups=[(40,123)]
        feed(p,n,groups)
        if n==350:
            first=deepcopy([ownership_record(g) for g in p._ownership_groups]);events=deepcopy(p.touch_events)
    assert len(events)==2 and p.touch_events==events
    assert [ownership_record(g) for g in p._ownership_groups]==first
    decisions={(d['source_id'],d['owner_id'],d['decided_sample']) for d in source_decisions(p)}
    assert len(decisions)==2
    g=next(g for g in p._ownership_groups if g['state']!='merged')
    assert first[1]['owner_id'] in g['competing_owner_ids']
    assert g['observed_samples']==sum(b-a for a,b in g['valid_sample_intervals'])
    evidence=group_release_evidence(p._ownership_groups,g['recovery']['owner_id'])
    assert not evidence['occupancy_valid'] and evidence['missing_reason']=='competing_source'


@pytest.mark.parametrize('mode',['walk','run'])
@pytest.mark.parametrize('duration',[30,31])
def test_short_window_boundary_is_independent_of_contact_confirmation(mode,duration):
    p,_,events=sequence(mode,True,joined=300+duration)
    assert bool(source_decisions(p)) == (duration==30)
    assert p.touch_events==events
    assert p.summary()['valid_contact_durations']==(1 if duration==30 else 0)


@pytest.mark.parametrize('mode',['walk','run'])
def test_mirrored_front_growth_does_not_require_positive_direction_or_other_foot(mode):
    p,_,events=sequence(mode,True,reverse=True)
    assert len(source_decisions(p))==1 and len(events)==1 and p.touch_events==events
    assert p.summary()['valid_contact_durations']==1
