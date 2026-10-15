"""Batch 2 review: source growth and competing thin-island publications."""
import pytest
from tests.test_ground_candidate_groups import make, feed, field_replay

def test_slow_unconfirmed_source_can_grow_after_connection():
    p=make('walk')
    for n in range(350):
        groups=[(40,47)] if 100<=n<177 else []
        if 152<=n<177:groups += [(49,49)]
        if 177<=n<188:groups=[(40,49)]
        if 188<=n<300:groups=[(40,56)]
        feed(p,n,groups)
    assert [e['touch_sample'] for e in p.touch_events if e['active']]==[100]
    g=next(g for g in p._ownership_groups if g.get('recovery'))
    assert g['recovery']['valid_sample_intervals']==[[100,189]]
    assert g['recovery']['unique_samples']==89

@pytest.mark.parametrize('grow', [False,True])
@pytest.mark.parametrize('distance', [3,50])
def test_later_island_needs_independent_evidence_near_recovered_foot(grow,distance):
    p=make('run')
    for n in range(450):
        groups=[(40,41),(44,45)] if n==100 else [(40,46)] if 101<=n<110 else [(40,60)] if 110<=n<350 else []
        if 200<=n<300:groups += [(60+distance,60+distance+(12 if grow and n>=220 else 0))]
        if distance==3 and not grow and 300<=n<350:groups=[(40,63)]
        feed(p,n,groups)
    starts=[e['touch_sample'] for e in p.touch_events if e['active']]
    assert starts==([100] if distance==3 and not grow else [100,200])
    if distance==3 and not grow:
        g=next(g for g in p._ownership_groups if g.get('recovery'))
        source=next(s for s in g['sources'] if s['first_sample']==200)
        assert source['observed_samples']==100
        assert source['valid_sample_intervals']==[[200,300]]
        assert source['evidence_at_join']['peak_width_m']==0


@pytest.mark.parametrize('field_replay', ['walk', 'run'], indirect=True)
def test_field_suspect_events_have_source_based_outcomes(field_replay):
    mode,p,_=field_replay
    if mode=='walk':
        events=[e for e in p.touch_events if e['touch_sample']==44935]
        assert len(events)==1 and events[0]['active']
        g=next(g for g in p._ownership_groups if g.get('recovery',{}).get('original_touch_sample')==44935)
        r=g['recovery']
        assert r['unique_samples']==sum(b-a for a,b in r['valid_sample_intervals'])
        assert r['budget_start_sample']==45012
        assert r['recovered_sample']>45012
        source=next(s for s in g['sources'] if s['first_sample']==44935)
        assert source['observed_samples']==77 and not source['evidence_at_join']['confirmed']
    else:
        assert not any(e['touch_sample']==103600 for e in p.touch_events)
        assert any(e['touch_sample']==103505 and e['active'] for e in p.touch_events)
        g=next(g for g in p._ownership_groups if any(s['first_sample']==103600 for s in g['sources']))
        source=next(s for s in g['sources'] if s['first_sample']==103600)
        assert source['observed_samples']==174
        assert source['valid_sample_intervals']==[[103600,103774]]
        assert source['evidence_at_join']['peak_width_m']==0
        assert not source['evidence_at_join'].get('confirmed',False)


def test_slow_growth_rejects_sustained_separation_and_late_added_sources():
    for late in [False,True]:
        p=make('walk')
        for n in range(500):
            if not late:
                groups=[(40,47),(49,49)] if 100<=n<177 else [(40,60)] if 177<=n<400 else []
            else:
                groups=[(40,41),(44,45)] if n==100 else [(40,46)] if 101<=n<400 else []
                if 250<=n<260:groups += [(49,49)]
                if 260<=n<400:groups=[(40,60)]
            feed(p,n,groups)
        assert not any(g.get('recovery') for g in p._ownership_groups)


def test_slow_growth_allows_later_short_lived_front_islands():
    p=make('walk')
    for n in range(350):
        groups=[(40,47)] if 100<=n<177 else []
        if 152<=n<177:groups += [(49,49)]
        if 165<=n<181:groups += [(51,51)]
        if 177<=n<181:groups += [(40,49)]
        if 181<=n<190:groups=[(40,51)]
        if 190<=n<300:groups=[(40,60)]
        feed(p,n,groups)
    g=next(g for g in p._ownership_groups if g.get('recovery'))
    assert g['recovery']['source_ids']==[s['source_id'] for s in g['sources']]
    assert len(g['sources'])==3 and p.reliable_touch_count==1
    assert g['observed_samples']==200 and g['valid_sample_intervals']==[[100,300]]

@pytest.mark.parametrize('remote_wide', [False, True])
def test_competing_island_remains_unknown_after_owner_clear(remote_wide):
    p=make('run')
    for n in range(450):
        groups=[(40,41),(44,45)] if n==100 else [(40,46)] if 101<=n<110 else [(40,60)] if 110<=n<280 else []
        if 200<=n<350:groups += [(63,63)]
        if remote_wide and 220<=n<360:groups += [(200,220)]
        feed(p,n,groups)
    assert [e['touch_sample'] for e in p.touch_events]==([100,220] if remote_wide else [100])
    decision=next(d for d in p.summary()['candidate_decisions'] if d['first_sample']==200)
    assert decision['outcome']=='unresolved'
    assert decision['observed_samples']==150
    assert decision['competing_group_id']==0
    assert decision['closed_sample']>=350
