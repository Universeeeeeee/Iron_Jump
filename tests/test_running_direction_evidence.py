"""Direction uses certified geometry without rewriting contact history."""
from copy import deepcopy
import pytest
from tests.test_ground_candidate_groups import make, feed
from tests.test_ground_ownership_publication import growing


def groups(n,starts,offsets,reverse=False):
    result=[]
    for start,offset in zip(starts,offsets):
        for lo,hi in growing(n-start+100):
            if reverse:lo,hi=767-hi-offset,767-lo-offset
            else:lo,hi=lo+offset,hi+offset
            result.append((lo,hi))
    return result


@pytest.mark.parametrize('reverse',[False,True])
def test_all_contacts_with_preserved_history_can_prove_direction_late(reverse):
    p=make('run')
    for n in range(752):feed(p,n,groups(n,[100,500],[0,60],reverse))
    assert p.direction==0 and p.reliable_touch_count==2
    ledger=deepcopy(p.touch_events)
    commits=deepcopy([e for e in p.event_audit if e['action']=='sequence_commit'])
    proven=[c for c in p.contacts if p._touch_events.get(c.id,{}).get('active')]
    assert all(c.problem=='unresolved_fragment_join' for c in proven)
    feed(p,752,[])
    assert p.direction==(-1 if reverse else 1)
    evidence=next(e for e in p.event_audit if e['action']=='direction_established')
    assert evidence['sample']==752
    assert evidence['contact_ids']==[0,2]
    assert p.touch_events==ledger
    assert [e for e in p.event_audit if e['action']=='sequence_commit']==commits
    assert all(c.problem=='unresolved_fragment_join' for c in proven)
    before=deepcopy(p.event_audit)
    p.summary();p.summary()
    assert p.event_audit==before


@pytest.mark.parametrize('reverse',[False,True])
def test_clean_direction_timing_unchanged(reverse):
    p=make('run')
    for n in range(610):
        gs=[(40,56)] if 100<=n<350 else [(100,116)] if 500<=n<750 else []
        if reverse:gs=[(767-hi,767-lo) for lo,hi in gs]
        feed(p,n,gs)
    assert p.direction==(-1 if reverse else 1)
    assert next(e for e in p.event_audit if e['action']=='direction_established')['sample']==559
    assert len([e for e in p.event_audit if e['action']=='publish'])==2


def test_stationary_separate_certified_contacts_do_not_prove_direction():
    p=make('run')
    for n in range(820):feed(p,n,groups(n,[100,500],[0,0]))
    assert p.reliable_touch_count==2 and p.direction==0 and not p.finished_reason
    assert not any(e['action']=='direction_established' for e in p.event_audit)


@pytest.mark.parametrize('reverse',[False,True])
def test_real_turn_with_historical_anomalies_is_still_detected(reverse):
    p=make('run')
    for n in range(1300):feed(p,n,groups(n,[100,500,900],[0,80,20],reverse))
    assert p.finished_reason=='turn_detected'
    assert p.last_sample==1152
    assert len([e for e in p.event_audit if e['action']=='direction_established'])==1
    assert any(e['action']=='direction_turn' and e['sample']==1152 for e in p.event_audit)
    assert p.reliable_touch_count==3


def test_late_old_geometry_is_not_a_new_turn():
    p=make('run')
    for n in range(1100):
        gs=[(lo+30,hi+30) for lo,hi in growing(n)] if n<350 else [(70,86)] if n<1000 else []
        if 500<=n<650:gs += [(20,35)]
        if 700<=n<850:gs += [(140,155)]
        feed(p,n,gs)
        if n==759:assert p.direction==1
    assert p.direction==1 and p.finished_reason is None
    assert p.reliable_touch_count==3
    assert not any(e['action']=='direction_turn' for e in p.event_audit)
