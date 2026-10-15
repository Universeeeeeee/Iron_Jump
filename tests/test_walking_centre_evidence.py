from copy import deepcopy
from types import SimpleNamespace
import pytest
from tests.test_ground_candidate_groups import make
from engine.modes.walking_processor import Contact
from engine.ground_position_evidence import walking_centre_position


def case():
    p=make('walk');p.last_sample=269
    c=Contact(0,0,'A','unknown',.1,.259,10,20,[p.positions[15]],end=.26,
              confirmed=True,exclusion='unresolved_fragment_join',position_known=False)
    source={'source_id':0,'first_sample':100,'joined_sample':121,'valid_sample_intervals':[[100,121]],
            'evidence_at_join':{'position_samples':[[100,10,20,[]],[120,10,20,[]]]}}
    g={'id':0,'recovery':{'owner_id':0,'source_ids':[0],'original_touch_sample':100,'recovered_sample':145,'rule_version':'test'},
       'sources':[source],'valid_sample_intervals':[[100,260]],'observation_runs':[[121,260,[[10,20]],True]],
       'tracking_end_reason':'reliable_clear','tracking_ended_sample':269,'occupancy_end_sample':260}
    p.contacts=[c];p._ownership_groups=[g]
    return p,c,g


def test_normal_footprint_sparse_definition_and_read_only():
    p,c,g=case();before=deepcopy((c,g));a=walking_centre_position(p,c);b=walking_centre_position(p,c)
    assert a==b and (c,g)==before
    value,e=a
    assert value==p.positions[15] and e['valid']
    assert [r['sample'] for r in e['inputs']]==list(range(100,260,20))
    assert c.position_known is False and c.exclusion=='unresolved_fragment_join'


def test_separate_owned_island_enters_original_centre_definition():
    p,c,g=case();s=deepcopy(g['sources'][0]);s.update(source_id=1,first_sample=110,valid_sample_intervals=[[110,121]])
    s['evidence_at_join']['position_samples']=[[110,22,22,[]],[120,22,22,[]]]
    g['sources'].append(s);g['recovery']['source_ids'].append(1)
    g['observation_runs']=[[121,260,[[10,22]],True]]
    value,e=walking_centre_position(p,c)
    row=next(r for r in e['inputs'] if r['sample']==120)
    assert row['centre_m']==p.positions[16] and set(row['sources'])=={'source:0','source:1'}
    assert value==p.positions[16]
    assert 110 not in [r['sample'] for r in e['inputs']]


def test_seed_values_use_original_grid_not_promotion_time():
    p,c,g=case();g['sources'][0]['joined_sample']=161
    g['sources'][0]['valid_sample_intervals']=[[100,161]]
    g['sources'][0]['evidence_at_join']['position_samples']=[[n,10,20,[]] for n in (100,120,140,160)]
    g['observation_runs']=[[161,260,[[10,20]],True]]
    value,e=walking_centre_position(p,c)
    assert e['valid'] and len(e['inputs'])==8
    assert 161 not in [r['sample'] for r in e['inputs']]


def test_duplicate_samples_are_one_centre_vote():
    p,c,g=case();g['sources'][0]['evidence_at_join']['position_samples']*=2
    g['observation_runs']=[[120,260,[[10,20]],True],[120,260,[[10,20]],True]]
    _,e=walking_centre_position(p,c)
    assert e['valid'] and len(e['inputs'])==8


def test_real_independent_foot_cannot_be_absorbed():
    p,c,g=case();g['sources'].append({'source_id':1,'evidence_at_join':{'confirmed':True}})
    assert walking_centre_position(p,c)[1]['missing_reason']=='unresolved_position_source'


def test_known_bad_inside_owned_envelope_stays_unknown():
    p,c,g=case();p.device=SimpleNamespace(bad_indices=(17,),layout=p.device.layout)
    c.exclusion='masked_contact_boundary'
    g['observation_runs']=[[121,260,[[10,14],[20,22]],True]]
    value,e=walking_centre_position(p,c)
    assert e['valid'] and value==p.positions[16]
    assert e['inputs'][-1]['unknown_indices']==[17]
    assert p.positions[17]==p.device.layout.positions_m[17]
    assert g['observation_runs'][0][2]==[[10,14],[20,22]]
    assert p._centre(c)['valid'] and c.exclusion=='masked_contact_boundary' and not c.position_known


@pytest.mark.parametrize('kind',['bad_outer','unknown_beam','unhealthy_run','missing_grid','missing_frame','masked_history','unclosed','estimated_time'])
def test_unknown_boundaries_and_windows_remain_unknown(kind):
    p,c,g=case()
    if kind=='bad_outer':p.device=SimpleNamespace(bad_indices=(10,),layout=p.device.layout)
    if kind=='unknown_beam':g['sources'][0]['evidence_at_join']['position_samples'][0][3]=[12]
    if kind=='unhealthy_run':g['observation_runs'][0][3]=False
    if kind=='missing_grid':g['sources'][0]['evidence_at_join']['position_samples'].pop(0)
    if kind=='missing_frame':g['observation_runs']=[[121,130,[[10,20]],True],[131,260,[[10,20]],True]]
    if kind=='masked_history':c.exclusion='masked_contact_boundary'
    if kind=='unclosed':g['tracking_end_reason']='interrupted'
    if kind=='estimated_time':c.edge_estimates['touch']=[99,101]
    assert not walking_centre_position(p,c)[1]['valid']


def test_cross_segment_coordinates_are_not_index_times_pitch():
    p,c,g=case();g['sources'][0]['evidence_at_join']['position_samples']=[[n,94,98,[]] for n in (100,120)]
    g['observation_runs']=[[121,260,[[94,98]],True]]
    value,e=walking_centre_position(p,c)
    assert e['valid'] and value==(p.positions[94]+p.positions[98])/2
    assert value!=96*p.device.layout.segments[0].pitch_m


def test_reverse_has_same_centre_reference():
    p,c,g=case();p.direction=-1
    assert walking_centre_position(p,c)[0]==p.positions[15]


def test_slow_translation_fails_representative_stability():
    p,c,g=case();c.end=.9;g.update(occupancy_end_sample=900,tracking_ended_sample=909,valid_sample_intervals=[[100,900]])
    g['observation_runs']=[[n,n+20,[[10+(n-120)//10,20+(n-120)//10]],True] for n in range(120,900,20)]
    assert walking_centre_position(p,c)[1]['missing_reason']=='unstable_representative_centre'


def test_birth_plus_grid_is_capped_at_one_hundred_values():
    p,c,g=case();c.start=.101;c.end=3.0;g['recovery']['original_touch_sample']=101
    g['sources'][0].update(first_sample=101,joined_sample=121,valid_sample_intervals=[[101,121]])
    g['sources'][0]['evidence_at_join']['position_samples']=[[101,10,20,[]],[120,10,20,[]]]
    g.update(occupancy_end_sample=3000,tracking_ended_sample=3009,valid_sample_intervals=[[101,3000]],observation_runs=[[121,3000,[[10,20]],True]])
    _,e=walking_centre_position(p,c)
    assert e['valid'] and len(e['inputs'])==100
    assert e['inputs'][0]['sample']==101 and e['inputs'][-1]['sample']==2080


def test_production_uses_independent_centre_certificate():
    p,c,g=case()
    assert p._centre(c)['valid']
    assert c.position_known is False and c.exclusion=='unresolved_fragment_join'




def test_production_seed_history_preserves_real_samples_without_duplicate_promotion():
    from tests.test_ground_candidate_groups import feed
    p=make('walk');p.config.min_contact_time=60
    for n in range(600):
        groups=[(10,30)] if 100<=n<580 else []
        if 300<=n<330:groups.append((100,100))
        elif 330<=n<340:groups.append((100,102))
        elif 340<=n<550:groups.append((100,109))
        feed(p,n,groups)
    c=next(c for c in p.contacts if round(c.start*1000)==300)
    assert [r[0] for r in c.position_samples]==list(range(300,550,20))
    assert c.position_samples[:3]==[[300,100,100,[]],[320,100,100,[]],[340,100,109,[]]]
    assert len({r[0] for r in c.position_samples})==len(c.position_samples)


@pytest.mark.parametrize('field_replay',['walk'],indirect=True)
def test_field_centres_keep_certified_positions_and_temporal_outputs_after_source_restoration(field_replay):
    import json
    from pathlib import Path
    _,p,_=field_replay;old=json.loads((Path(__file__).parents[1]/'exports/ground_position_rebuild_D_20261011/after/walk/summary.json').read_text())
    before=deepcopy((p.contacts,p._ownership_groups,p.event_audit))
    new=p.summary()
    assert new==p.summary() and (p.contacts,p._ownership_groups,p.event_audit)==before
    restored={e['owner_id'] for e in new['event_audit'] if e['action']=='source_uncertainty_resolved'}
    assert new['event_publications']==old['event_publications']
    assert [e for e in new['event_audit'] if e['action']!='source_uncertainty_resolved']==old['event_audit']
    assert new['cycles']==old['cycles']
    for a,b in zip(new['contacts'],old['contacts']):
        changed={'position_m','centre_m'}
        if a['id'] in restored:
            changed |= {'position_known','exclusion','merged_interruptions'}
            assert a['position_known'] and a['exclusion'] is None
        assert {k:v for k,v in a.items() if k not in changed}=={k:v for k,v in b.items() if k not in changed}
    for a,b in zip(new['steps'],old['steps']):
        assert (a['from_id'],a['to_id'],a['time_s'])==(b['from_id'],b['to_id'],b['time_s'])
    for cid in (4,5,9,12):assert new['contacts'][cid]['position_m']==old['contacts'][cid]['position_m']
    for cid in (0,3,8,10,13):
        assert new['contacts'][cid]['centre_m']['valid']
        if cid not in restored:
            assert not new['contacts'][cid]['position_known'] and new['contacts'][cid]['exclusion']
    for cid in (6,11):assert not new['contacts'][cid]['centre_m']['valid']
    x=new['contacts'][13]
    assert x['position_m']==pytest.approx(7.429) and p.contacts[13].position==pytest.approx(7.429)
    for cid,n,expected in [(0,42380,.2132),(8,45740,3.7020)]:
        evidence=new['contacts'][cid]['centre_m']['evidence']
        assert next(r['centre_m'] for r in evidence['inputs'] if r['sample']==n)==pytest.approx(expected)
    assert [r['sample'] for r in new['contacts'][10]['centre_m']['evidence']['inputs']][:3]==[47000,47020,47040]
    assert [r['sample'] for r in x['centre_m']['evidence']['inputs']][:4]==[49151,49160,49180,49200]


from tests.test_ground_candidate_groups import field_replay
