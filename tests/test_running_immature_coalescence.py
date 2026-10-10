"""An optical coalescence is evidence of a group, not proof of one foot."""
from dataclasses import replace
import pytest
from tests.test_overground_running import processor,frame


def replay(*,anchor=False,kind='async'):
 p=processor(3,starting_foot='Left',min_contact_time=60)
 for n in range(1100):
  bounds=[(.05,.2)] if anchor and 20<=n<500 else[]
  join=315 if kind=='late' else 303
  second=300 if kind=='simultaneous' else 302
  if 300<=n<join:
   bounds +=[(.5,.55)] if kind=='wide' or kind=='shrink' and n==300 else[(.51,.53)]
  if second<=n<join:bounds +=[(.61,.63)] if kind=='two_beams' else[(.62,.63)]
  if join<=n<550:bounds +=[(.50,.72)]
  if 650<=n<800:bounds +=[(1.1,1.3)]
  if 900<=n<1050:bounds +=[(1.8,2.0)]
  if kind=='gap' and n==302:continue
  p.process(frame(p.device.layout,n,bounds))
 return p


@pytest.mark.parametrize('anchor',[False,True])
@pytest.mark.parametrize('kind',['async','two_beams'])
def test_immature_coalescence_preserves_sources_and_later_healthy_relations(anchor,kind):
 p=replay(anchor=anchor,kind=kind);s=p.summary()
 assert not any(x['code']=='ambiguous_contacts' for x in p.issues)
 parent=next(c for c in p.contacts if c.start==300 and c.candidate_outcome!='associated_fragment')
 assert parent.problem=='unresolved_coalescence' and not parent.touch_known
 row=s['contacts'][parent.id]
 assert row['first_seen_sample']==300 and row['touch_sample'] is None
 assert not row['toe_m']['valid'] and parent.side=='unknown' and not parent.label
 assert parent.end==550 and parent.observed_samples==250
 sources=[x for x in s['candidate_decisions'] if x['reason']=='immature_islands_coalesced']
 assert {x['first_sample'] for x in sources}=={300,302}
 assert all(x['owner_id']==parent.id for x in sources)
 assert s['steps'][-1]['time_s']['valid'] and s['steps'][-1]['time_s']['value']==pytest.approx(.25)
 if not anchor:assert s['duration_s'] is None


@pytest.mark.parametrize('kind',['late','simultaneous','wide','shrink','gap'])
def test_unproven_merge_is_never_labeled_local_immature_coalescence(kind):
 p=replay(kind=kind)
 assert not any(x['reason']=='immature_islands_coalesced' for x in p.summary()['candidate_decisions'])


def test_single_person_two_feet_may_span_three_modules():
 p=processor(3,min_contact_time=60)
 for n in range(600):
  bounds=[(.88,1.18)] if 100<=n<350 else[]
  if 200<=n<450:bounds +=[(1.73,2.03)]
  p.process(frame(p.device.layout,n,bounds))
 assert not p.issues and len(p.contacts)==2
 assert all(c.confirmed and c.touch_known for c in p.contacts)
 assert p.summary()['valid_steps']==1


@pytest.mark.parametrize('grows',[False,True])
def test_isolated_far_single_beam_can_close_without_mature_owner_but_growth_is_not_noise(grows):
 p=processor(3,min_contact_time=60)
 for n in range(600):
  bounds=[(.2,.4)] if 100<=n<400 else[]
  if 110<=n<450:bounds +=[(.8,1.0)]
  if n==120 or grows and 120<=n<130:bounds +=[(p.positions[220],p.positions[220])]
  if grows and 130<=n<350:bounds +=[(2.2,2.4)]
  p.process(frame(p.device.layout,n,bounds))
 if grows:
  assert any(x['code']=='ambiguous_contacts' and x['sample']==130 for x in p.issues)
  assert not any(x['outcome']=='excluded_nonstep' for x in p.summary()['candidate_decisions'])
 else:
  assert not p.issues and len(p.contacts)==2
  assert p.summary()['valid_steps']==1
  assert any(x['first_sample']==120 and x['outcome']=='excluded_nonstep' for x in p.summary()['candidate_decisions'])


def test_unknown_terminal_group_cannot_supply_direction_turn_or_exit():
 p=processor(3,min_contact_time=60)
 for n in range(1800):
  bounds=[]
  if 100<=n<103:bounds=[(2.82,2.84)]
  if n==102:bounds +=[(2.92,2.93)]
  if 103<=n<350:bounds=[(2.80,3.0)]
  if 450<=n<650:bounds +=[(.2,.4)]
  if 800<=n<1000:bounds +=[(.9,1.1)]
  p.process(frame(p.device.layout,n,bounds))
 assert not p.issues and p.finished_reason is None
 assert p.contacts[0].problem=='unresolved_coalescence'
 assert p.direction==1 and not p._exit_evidence
 assert p.contacts[-1].end==1000 and p.summary()['steps'][-1]['time_s']['valid']


@pytest.mark.parametrize('kind',['coalescence','remote_bad'])
def test_later_uncertainty_before_confirmation_does_not_erase_earlier_known_entry(kind):
 from engine.modes.overground_running_processor import OvergroundRunningProcessor
 from hardware.walking_preflight import PreparedDevice
 p=processor(8,min_contact_time=60)
 if kind=='remote_bad':p=OvergroundRunningProcessor(p.config,PreparedDevice(p.device.layout,'running',-1,0,1000,bad_indices=(576,)))
 for n in range(800):
  bounds=[(.2,.4)] if 20<=n<350 else[]
  if kind=='coalescence':
   if 50<=n<53:bounds +=[(.5,.53)]
   if n==52:bounds +=[(.62,.63)]
   if 53<=n<500:bounds +=[(.5,.72)]
  elif 50<=n<500:bounds +=[(6.0104,6.2)]
  if 550<=n<700:bounds +=[(1.1,1.3)] if kind=='coalescence' else[(7.0,7.2)]
  p.process(frame(p.device.layout,n,bounds),masked_contact=kind=='remote_bad' and 50<=n<500)
 assert p.origin==.02
 assert p.summary()['contacts'][0]['touch_s']['valid']
 assert p.summary()['duration_s']==pytest.approx(.68)
