"""Ordinary contact provenance must survive a neighbouring group's recovery."""
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec
from copy import deepcopy
import pytest
from engine.overground_session import OvergroundSession
from tests.test_ground_candidate_groups import make
from tests.test_running_pending_growth import sample
from tests.test_ground_ownership_publication import growing


def field_replay(stop):
    root=Path(__file__).parents[1]
    spec=spec_from_file_location('minimal_replay',root/'exports/ground_minimal_fixes_F_20261011/replay.py')
    module=module_from_spec(spec);spec.loader.exec_module(module)
    return module.replay(root/'exports/ground_field_acceptance_F_20261011/captured/session_05/run_forward_02','run',stop=stop)


def test_field_7991_8022_8050_keeps_ordinary_contact_competition(qtbot):
    p,s,states=field_replay(8090)
    c=next(c for c in p.contacts if c.first_seen_sample==7991)
    assert not any(e['active'] and e['touch_sample']==7991 for e in p.touch_events)
    assert c.observed_samples==66 and c.valid_sample_intervals==[[7991,8057]]
    assert c.end==8057 and c not in p.active
    assert c.ownership_competition[0]['group_id']==2
    assert c.ownership_competition[0]['outcome']=='unresolved'
    assert states[7991]['contacts'][c.id]['ownership_competition'][0]['detected_sample']==7991
    assert states[8022]['groups'][2]['recovery']['recovered_sample']==8022
    assert not any(e['touch_sample']==7991 for e in states[8050]['events'])
    row=s['contacts'][c.id]
    assert all(not row[k]['valid'] for k in ('touch_s','lift_s','toe_m','contact_s'))


@pytest.mark.parametrize('first',[20,90,130,170])
@pytest.mark.parametrize('kind',['near_narrow','far_narrow','near_growth'])
def test_source_order_and_independent_growth(qtbot,first,kind):
    p=make('run'); session=OvergroundSession(p.config,type(p));session.start_prepared(p.device)
    for n in range(410):
        groups=growing(n)
        if first<=n<370:
            lo=200 if kind=='far_narrow' else 38
            groups += [(lo-3 if kind=='near_growth' and n>=first+20 else lo,lo)]
        session.on_frame(sample(p,n,groups))
    session.halt();p=session.processor
    c=next((c for c in p.contacts if c.first_seen_sample==first),None)
    if c is None:
        assert kind=='near_narrow' and first==170
        decision=next(r for r in p._candidate_decisions if r['first_sample']==first)
        assert decision['observed_samples']==370-first and decision['outcome']=='unresolved'
        assert not any(e['touch_sample']==first for e in p.touch_events)
        return
    assert c.observed_samples==370-first
    assert bool(p._touch_events.get(c.id,{}).get('active'))==(kind!='near_narrow' or first==20)
    # A pre-existing independently confirmed source stays published.
    if kind=='near_narrow' and first!=20:
        assert c.ownership_competition and c.candidate_outcome!='associated_fragment'
    elif kind=='near_growth':
        assert c.peak_width_m>=p.NARROW_CANDIDATE_WIDTH_M
    before=deepcopy((p.touch_events,p.event_audit,p._ownership_groups))
    p.build_report('manual');p.summary();p.summary()
    assert before==(p.touch_events,p.event_audit,p._ownership_groups)


def test_two_mature_bodies_keep_existing_touches(qtbot):
    p=make('run');session=OvergroundSession(p.config,type(p));session.start_prepared(p.device)
    for n in range(500):
        groups=[(40,56)] if 100<=n<400 else []
        if 170<=n<400:groups += [(65,81)]
        if 250<=n<400:groups=[(40,81)]
        session.on_frame(sample(p,n,groups))
    session.halt();p=session.processor
    assert p.reliable_touch_count==2
    assert not any(g.get('recovery') for g in p._ownership_groups)
