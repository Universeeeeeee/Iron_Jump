"""Independent single-foot return and real new-foot timing contracts."""
import pytest
from engine.overground_session import OvergroundSession
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.sensor_frame import DeviceLayout
from hardware.walking_preflight import PreparedDevice
from tests.test_overground_running import frame,processor


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('wire_order',[None,(3,1,2)])
def test_known_forefoot_with_brief_returning_heel_keeps_contact(qtbot,reverse,filtered,wire_order):
    p=processor(3,starting_foot='Left')
    if wire_order is not None:
        layout=DeviceLayout.linear(3,wire_order=wire_order)
        p=OvergroundRunningProcessor(p.config,PreparedDevice(layout,'running',-1,0,1000))
    session=OvergroundSession(p.config,type(p)) if filtered else None
    if session:session.start_prepared(p.device)
    for n in range(600):
        bounds=[]
        if 100<=n<450:bounds=[(.47,.68)]
        if 200<=n<305:bounds=[(.53,.68)]
        if 300<=n<305:bounds +=[(.47,.49)]
        if reverse:bounds=[(3-b,3-a) for a,b in bounds]
        f=frame(p.device.layout,n,bounds)
        if session:session.on_frame(f)
        else:p.process(f)
    if session:
        session.halt();p=session.processor
        assert session.build_report('manual').export_frames[300]==frame(p.device.layout,300,[(2.32,2.47),(2.51,2.53)] if reverse else[(.53,.68),(.47,.49)]).contact_bits
    assert len(p.contacts)==1
    assert not p.issues
    assert p.contacts[0].start==100 and p.contacts[0].end==450
    assert p.contacts[0].confirmed and p.contacts[0].side=='left'
    assert p.summary()['contacts'][0]['contact_s']['value']==pytest.approx(.35)
    assert p._support(290,310,p.contacts[0].epoch)[0] is None


@pytest.mark.parametrize('grow',[False,True])
def test_true_narrow_new_foot_promotes_with_original_touch_and_samples(grow):
    p=processor(3,starting_foot='Left')
    for n in range(800):
        bounds=[]
        if 100<=n<400:bounds=[(.47,.68)]
        if 300<=n<450:
            bounds +=[(.91,.92)] if not grow or n<305 else[(.88,1.03)]
        if 600<=n<750:bounds=[(1.4,1.55)]
        p.process(frame(p.device.layout,n,bounds))
    assert len(p.contacts)==3 and not p.issues
    new=p.contacts[1]
    assert new.start==300 and new.end==450 and new.observed_samples==150
    assert new.confirmed and new.side=='right'
    assert new.edges[0][0]==300
    s=p.summary()
    assert s['steps'][0]['time_s']['value']==pytest.approx(.2)
    assert s['cycles'][0]['duration_s']['valid']
    assert s['cycles'][0]['single_support_s']['value']==pytest.approx(.25)
    assert s['cycles'][0]['double_support_s']['value']==pytest.approx(.1)


def test_initial_islands_without_confirmed_anchor_are_not_deferred():
    p=processor()
    for n in range(400):
        bounds=[]
        if 100<=n<105:bounds=[(.47,.49),(.54,.56)]
        if 105<=n<250:bounds=[(.48,.65)]
        p.process(frame(p.device.layout,n,bounds))
    assert any(i['code']=='ambiguous_contacts' for i in p.issues)


@pytest.mark.parametrize('barrier',['gap','invalid','mask'])
def test_pending_candidates_never_cross_quality_barrier(barrier):
    from dataclasses import replace
    p=processor()
    for n in range(500):
        bounds=[(.47,.68)] if 100<=n<400 else[]
        if 300<=n<330:bounds +=[(.91,.92)]
        if n==305 and barrier=='gap':continue
        f=frame(p.device.layout,n,bounds)
        if n==305 and barrier=='invalid':f=replace(f,valid_bits=b'\x00'*f.layout.bit_count)
        p.process(f,masked_contact=n==305 and barrier=='mask')
    recovered=[c for c in p.contacts if c.start>305]
    assert recovered
    assert all(c.start>=306 for c in recovered)
    assert any(i['code'] in ['frame_gap','invalid_sample','masked_contact_boundary'] for i in p.issues)


def test_wide_third_contact_and_confirmed_merge_remain_ambiguous():
    p=processor()
    for n in range(500):
        bounds=[(.48,.68),(.88,1.08)] if 100<=n<350 else[]
        if 200<=n<300:bounds +=[(1.5,1.65)]
        p.process(frame(p.device.layout,n,bounds))
    assert any(i['code']=='ambiguous_contacts' for i in p.issues)


def test_pending_new_interior_touch_revokes_terminal_proof_even_if_it_merges_back():
    p=processor(1)
    for n in range(1600):
        bounds=[]
        if 100<=n<250:bounds=[(.15,.3)]
        if 400<=n<550:bounds=[(.45,.6)]
        if 700<=n<920:bounds=[(.82,.99 if 820<=n<840 or 865<=n<880 else .96)]
        if 850<=n<855:bounds +=[(.75,.76)]
        if 855<=n<865:bounds=[(.75,.96)]
        p.process(frame(p.device.layout,n,bounds))
    assert len(p.contacts)==3
    assert not p.issues
    assert p.finished_reason is None
    assert not p._exit_evidence


def test_released_short_island_is_a_sequence_barrier_without_erasing_known_contact():
    p=processor(3,starting_foot='Left')
    for n in range(900):
        bounds=[]
        if 100<=n<400:bounds=[(.47,.68)]
        if 250<=n<255:bounds +=[(.91,.92)]
        if 450<=n<600:bounds=[(.88,1.05)]
        if 700<=n<850:bounds=[(1.4,1.55)]
        p.process(frame(p.device.layout,n,bounds))
    s=p.summary()
    assert len(p.contacts)==3 and not p.issues
    assert s['contacts'][0]['contact_s']['valid']
    assert not s['steps'][0]['time_s']['valid']
    assert s['steps'][1]['time_s']['valid']
    assert not s['cycles'][0]['duration_s']['valid']
    assert p.contacts[1].side=='unknown'


def test_two_pending_islands_joining_without_existing_owner_are_ambiguous():
    p=processor(3)
    for n in range(500):
        bounds=[(.47,.68)] if 100<=n<400 else[]
        if 300<=n<305:bounds +=[(.91,.92),(.98,.99)]
        if 305<=n<350:bounds +=[(.91,.99)]
        p.process(frame(p.device.layout,n,bounds))
    assert any(i['code']=='ambiguous_contacts' for i in p.issues)


def test_later_wide_contact_cannot_overtake_earlier_pending_touch():
    p=processor(3)
    for n in range(600):
        bounds=[(.47,.68)] if 100<=n<400 else[]
        if 300<=n<350:bounds +=[(.91,.92)]
        if 305<=n<360:bounds +=[(1.5,1.65)]
        p.process(frame(p.device.layout,n,bounds))
    assert any(i['code']=='ambiguous_contacts' for i in p.issues)
    assert all(a.start<=b.start for a,b in zip(p.contacts,p.contacts[1:]))


def test_new_foot_on_first_pending_absence_cannot_publish_certain_side():
    p=processor(3,starting_foot='Left',min_contact_time=60)
    for n in range(600):
        bounds=[]
        if 100<=n<400:bounds=[(p.positions[20],p.positions[40])]
        if 220<=n<226:bounds +=[(p.positions[150],p.positions[150])]
        if 226<=n<500:bounds +=[(p.positions[85],p.positions[105])]
        p.process(frame(p.device.layout,n,bounds))
    assert not p.issues and len(p.contacts)==2
    assert p.contacts[0].side=='left' and p.contacts[0].confirmed
    assert p.contacts[1].start==226 and p.contacts[1].confirmed
    assert p.contacts[1].side=='unknown'
    assert not p.summary()['steps'][0]['time_s']['valid']


@pytest.mark.parametrize('segments',[1,3,8,12])
@pytest.mark.parametrize('reverse',[False,True])
def test_same_returning_heel_trajectory_across_device_lengths(segments,reverse):
    p=processor(segments)
    for n in range(600):
        bounds=[(.47,.68)] if 100<=n<450 else[]
        if 200<=n<305:bounds=[(.53,.68)]
        if 300<=n<305:bounds +=[(.47,.49)]
        if reverse:bounds=[(segments-b,segments-a) for a,b in bounds]
        p.process(frame(p.device.layout,n,bounds))
    assert len(p.contacts)==1 and not p.issues
    assert p.contacts[0].start==100 and p.contacts[0].end==450
    assert p.summary()['duration_s']==pytest.approx(.35)


def test_boundary_narrow_new_contact_is_never_deferred():
    p=processor(3,stop_type='Software command')
    for n in range(400):
        bounds=[(.47,.68)] if 100<=n<350 else[]
        if 250<=n<290:bounds +=[(p.positions[-1],p.positions[-1])]
        p.process(frame(p.device.layout,n,bounds))
        if n==250:assert len(p.contacts)==2
    assert p.contacts[-1].start==250 and p.contacts[-1].confirmed
    assert not p.contacts[-1].touch_known


def test_fresh_terminal_contact_can_establish_proof_after_pending_barrier():
    p=processor(1)
    for n in range(1800):
        bounds=[]
        if 100<=n<250:bounds=[(.15,.3)]
        if 400<=n<550:bounds=[(.45,.6)]
        if 700<=n<920:bounds=[(.82,.99 if 820<=n<840 or 865<=n<880 else .96)]
        if 850<=n<855:bounds +=[(.75,.76)]
        if 855<=n<865:bounds=[(.75,.96)]
        if 1100<=n<1200:bounds=[(.82,.99)]
        p.process(frame(p.device.layout,n,bounds))
    assert not p.issues and len(p.contacts)==4
    assert p.finished_reason=='passage_complete' and p.last_sample==1699
    assert p._exit_contact_id==3
