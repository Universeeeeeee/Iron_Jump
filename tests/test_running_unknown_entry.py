"""Unknown early activity cannot become a seemingly complete later passage."""
from dataclasses import replace
import pytest
from engine.overground_session import OvergroundSession
from tests.test_overground_running import frame,processor


@pytest.mark.parametrize('kind',['gap','invalid','ambiguity','simultaneous','boundary','short_clear'])
@pytest.mark.parametrize('known_prefix',[False,True])
def test_unknown_entry_preserves_missing_origin_without_erasing_known_passage(qtbot,kind,known_prefix):
 p=processor(3,min_contact_time=60,stop_type='Software command')
 for n in range(700):
  if kind=='gap' and n==129:continue
  bounds=[(.08,.23)] if known_prefix and 20<=n<90 else[]
  if kind in {'gap','invalid'}:
   if 130<=n<350:bounds +=[(.5,.7)]
  elif kind=='short_clear':
   if 100<=n<120:bounds +=[(.5,.53)]
   if 121<=n<350:bounds +=[(.55,.57)]
  elif 100<=n<350:
   bounds +=[(0,.2)] if kind=='boundary' else[(.5,.7)]
   if kind=='simultaneous':bounds +=[(.9,1.1)]
  if kind=='ambiguity' and n==130:bounds=[(.5,1.2)]
  if 400<=n<550:bounds +=[(1.6,1.8)]
  f=frame(p.device.layout,n,bounds)
  if kind=='invalid' and n==129:f=replace(f,valid_bits=b'\x00'*p.device.layout.bit_count)
  p.process(f)
 assert p.summary()['contacts'][-1]['touch_s']['valid']
 assert p.summary()['contacts'][-1]['contact_s']['valid']
 if known_prefix:
  assert p.origin==.02 and p.summary()['duration_s']==pytest.approx(.53)
 else:
  assert p.origin==.4 and p.summary()['duration_s'] is None


@pytest.mark.parametrize('kind',['gap','short_clear'])
def test_formal_filter_keeps_unknown_first_entry_missing(qtbot,kind):
 p=processor(3,min_contact_time=60,stop_type='Software command')
 session=OvergroundSession(p.config,type(p));session.start_prepared(p.device)
 raw=[]
 for n in range(700):
  if kind=='gap' and n==129:continue
  bounds=[]
  if kind=='gap' and 130<=n<350:bounds=[(.5,.7)]
  if kind=='short_clear' and 100<=n<120:bounds=[(.5,.53)]
  if kind=='short_clear' and 121<=n<350:bounds=[(.55,.57)]
  if 400<=n<550:bounds +=[(1.6,1.8)]
  f=frame(p.device.layout,n,bounds);raw.append(f.contact_bits);session.on_frame(f)
 session.halt();p=session.processor
 assert p.origin==.4 and p.summary()['duration_s'] is None
 assert session.build_report('manual').export_frames==tuple(raw)


def test_empty_gap_before_reliable_entry_does_not_invent_unknown_activity():
 p=processor(3,min_contact_time=60)
 for n in range(500):
  if n==129:continue
  p.process(frame(p.device.layout,n,[(.5,.7)] if 200<=n<350 else[]))
 assert p.origin==.2 and p.summary()['duration_s']==pytest.approx(.15)


@pytest.mark.parametrize('filtered',[False,True])
@pytest.mark.parametrize('known_prefix',[False,True])
def test_initial_unowned_ambiguity_cannot_publish_partial_duration(qtbot,filtered,known_prefix):
 p=processor(3,min_contact_time=60,stop_type='Software command')
 session=OvergroundSession(p.config,type(p)) if filtered else None
 if session:session.start_prepared(p.device)
 for n in range(700):
  bounds=[(.08,.23)] if known_prefix and 20<=n<90 else[]
  if 100<=n<250:bounds +=[(.5,.7),(1.05,1.25),(1.6,1.8)]
  if 400<=n<550:bounds +=[(2.2,2.4)]
  f=frame(p.device.layout,n,bounds)
  if session:session.on_frame(f)
  else:p.process(f)
 if session:session.halt();p=session.processor
 assert [i['code'] for i in p.issues]==['ambiguous_contacts']
 assert p.summary()['duration_s']==(pytest.approx(.53) if known_prefix else None)


@pytest.mark.parametrize('healthy_start',[90,99])
def test_unknown_boundary_uses_lower_bound_before_recovering_origin(healthy_start):
 from tests.test_ground_local_observation import processor,replay,sample
 p=processor('run',min_contact_time=60)
 frames=[]
 for n in range(700):
  bounds=[(1.2,1.38)] if healthy_start<=n<350 else[]
  if 100<=n<300:bounds +=[(0,.18)]
  if 400<=n<550:bounds +=[(2.2,2.38)]
  frames.append(sample(n,bounds,[0] if 96<=n<105 else[]))
 replay(p,frames)
 boundary=next(c for c in p.contacts if not c.touch_known)
 assert boundary.start==100 and boundary.edge_estimates['touch']==[95,105]
 assert p.origin==healthy_start/1000 and not p.issues
 assert p.summary()['duration_s']==(pytest.approx(.46) if healthy_start==90 else None)


@pytest.mark.parametrize('kind',['short','interruption'])
def test_unconfirmed_initial_activity_cannot_be_ignored_by_later_origin(kind):
 p=processor(3,min_contact_time=60,stop_type='Software command')
 for n in range(700):
  if kind=='interruption' and n==130:continue
  bounds=[(.5,.7)] if 100<=n<140 else[]
  if 400<=n<550:bounds +=[(1.6,1.8)]
  p.process(frame(p.device.layout,n,bounds))
 assert p.origin==.4 and p.summary()['duration_s'] is None
 assert p.summary()['contacts'][-1]['contact_s']['valid']


@pytest.mark.parametrize('samples',[1,2])
def test_only_closed_isolated_nonstep_may_be_excluded_before_entry(samples):
 p=processor(3,min_contact_time=60,stop_type='Software command')
 for n in range(700):
  bounds=[(p.positions[60],p.positions[60])] if 100<=n<100+samples else[]
  if 400<=n<550:bounds +=[(1.6,1.8)]
  p.process(frame(p.device.layout,n,bounds))
 assert p.origin==.4
 assert p.contacts[0].candidate_outcome==('excluded_nonstep' if samples==1 else 'unresolved')
 assert p.summary()['duration_s']==(pytest.approx(.15) if samples==1 else None)
