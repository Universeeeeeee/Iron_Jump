from copy import deepcopy
from types import SimpleNamespace
import pytest
from engine.ground_position_evidence import running_position_history
from engine.modes.overground_running_processor import Contact
from tests.test_ground_candidate_groups import make


def case():
    p=make('run')
    c=Contact(0,0,'A','unknown',100,119,10,14,True,end=120,confirmed=True,problem='unresolved_fragment_join',edges=[[100,106,10,11]])
    p.contacts=[c]
    g={'id':0,'recovery':{'owner_id':0,'source_ids':[0], 'original_touch_sample':100,'recovered_sample':115,'rule_version':'test'},
       'sources':[{'source_id':0,'valid_sample_intervals':[[100,106]],'evidence_at_join':{'edges':deepcopy(c.edges)}}],
       'valid_sample_intervals':[[100,120]],'last_sample':119,'occupancy_end_sample':120,'tracking_ended_sample':122,
       'tracking_end_reason':'reliable_clear','observation_runs':[[106,120,[[10,14]],True]]}
    p._ownership_groups=[g];p.direction=1
    return p,c,g


def toe(p,c,edges):
    x=deepcopy(c);x.problem=None;x.edges=edges
    return p._toe(x)


def test_prefix_platform_does_not_hide_later_further_platform():
    p,c,g=case();edges,e=running_position_history(p,c)
    assert e['valid'] and e['evidence_available_sample']==122
    assert toe(p,c,c.edges)['value']==p.positions[11]
    assert toe(p,c,edges)['value']==p.positions[14]


def test_same_sample_union_not_extra_votes():
    p,c,g=case();g['observation_runs'].insert(0,[100,106,[[10,11]],True])
    edges,e=running_position_history(p,c)
    assert sum(b-a for a,b,*_ in edges)==20==e['unique_samples']


def test_disconnected_islands_use_owned_front_without_filling_time():
    p,c,g=case();g['observation_runs']=[[106,120,[[10,11],[14,14]],True]]
    edges,e=running_position_history(p,c)
    assert e['valid'] and toe(p,c,edges)['value']==p.positions[14]


@pytest.mark.parametrize('change',['missing','unhealthy','bad_beam','unknown_source','masked','not_closed'])
def test_preserve_incomplete_windows(change):
    p,c,g=case()
    if change=='missing':g['observation_runs'][0][0]=107
    if change=='unhealthy':g['observation_runs'][0][3]=False
    if change=='bad_beam':p.device=SimpleNamespace(bad_indices=(14,),layout=p.device.layout)
    if change=='unknown_source':g['sources'].append({'source_id':2})
    if change=='masked':c.first_masked_sample=110
    if change=='not_closed':g['tracking_end_reason']=None
    assert not running_position_history(p,c)[1]['valid']


def test_real_gap_cannot_create_five_ms_platform():
    p,c,g=case();c.edges=[[100,102,10,14]];g['sources'][0]['evidence_at_join']['edges']=deepcopy(c.edges)
    g['observation_runs']=[[103,106,[[10,14]],True],[106,120,[[10,11]],True]]
    assert not running_position_history(p,c)[1]['valid']


def test_cross_segment_uses_calibrated_positions():
    p,c,g=case();c.edges=[[100,106,90,94]];g['sources'][0]['evidence_at_join']['edges']=deepcopy(c.edges)
    g['observation_runs']=[[106,120,[[94,98]],True]]
    edges,e=running_position_history(p,c)
    assert e['valid'] and toe(p,c,edges)['value']==p.positions[98]


def test_reconstruction_does_not_mutate_history():
    p,c,g=case();before=deepcopy((c,g));a=running_position_history(p,c);b=running_position_history(p,c)
    assert a==b and (c,g)==before


def test_integration_uses_complete_history_preserves_audit():
    p,c,g=case();before=deepcopy((c,g))
    result=p._toe(c)
    assert result['valid'] and result['value']==p.positions[14]
    assert (c,g)==before and c.problem=='unresolved_fragment_join'


def test_segment_seam_does_not_fake_a_stable_platform():
    p,c,g=case()
    assert p.positions[96]-p.positions[95] > p.device.layout.segments[0].pitch_m
    result=toe(p,c,[[100,103,90,95],[103,106,90,96]])
    assert not result['valid'] and result['missing_reason']=='no_stable_toe_platform'


def test_negative_direction_selects_rear_edge_in_coordinates():
    p,c,g=case();p.direction=-1;g['observation_runs']=[[106,120,[[8,14]],True]]
    edges,e=running_position_history(p,c)
    assert e['valid'] and toe(p,c,edges)['value']==p.positions[8]


def test_unclosed_or_unknown_window_never_overrides_rejection():
    p,c,g=case();g['sources'].append({'source_id':1})
    assert not p._toe(c)['valid']
    assert c.problem=='unresolved_fragment_join'


@pytest.mark.parametrize('field_replay',['run'],indirect=True)
def test_field_spatial_rebuild_is_pure_and_temporal_ledger_unchanged(field_replay):
    import json
    from pathlib import Path
    _,p,_=field_replay
    before=deepcopy((p.contacts,p._ownership_groups,p.event_audit))
    s=p.summary()
    assert s==p.summary() and (p.contacts,p._ownership_groups,p.event_audit)==before
    baseline=json.loads((Path(__file__).parents[1]/'exports/ground_source_review_B_20261011/after/run/filtered_summary.json').read_text())
    for key,excluded in [('contacts',{'toe_m'}),('steps',{'length_m','speed_m_s'}),('cycles',{'length_m'})]:
        assert len(s[key])==len(baseline[key])
        for a,b in zip(s[key],baseline[key]):
            assert {k:v for k,v in a.items() if k not in excluded}=={k:v for k,v in b.items() if k not in excluded}
    assert s['event_publications']==baseline['event_publications']
    added_actions={'contact_competition','direction_established','direction_turn'}
    assert [e for e in s['event_audit'] if e['action'] not in added_actions]==baseline['event_audit']
    # New provenance/direction audit entries must not rewrite the event ledger.
    for e in s['event_audit']:
        if e['action']=='contact_competition' and e['outcome']=='associated':
            from engine.ground_source_review import assigned_sources
            assert e['source_id'] in assigned_sources(p._ownership_groups[e['group_id']])
    for a,b in zip(s['contacts'],baseline['contacts']):
        if b['toe_m']['valid']:assert a['toe_m']==b['toe_m']
    recovered={r['touch_sample']:r['toe_m'] for r in s['contacts'] if r['toe_m'].get('evidence',{}).get('valid')}
    assert set(recovered)=={102291,102723,103903,104264,105473}
    assert all(m['evidence']['evidence_available_sample']>m['evidence']['window'][1] for m in recovered.values())


from tests.test_ground_candidate_groups import field_replay


def test_bad_beam_between_owned_islands_is_not_a_healthy_window():
    p,c,g=case();p.device=SimpleNamespace(bad_indices=(17,),layout=p.device.layout)
    g['observation_runs']=[[106,120,[[10,11],[20,20]],True]]
    assert not running_position_history(p,c)[1]['valid']


def test_integral_estimated_clock_does_not_change_sample_union():
    p,c,g=case();c.start=100.0;c.end=120.0
    assert running_position_history(p,c)[1]['unique_samples']==20
