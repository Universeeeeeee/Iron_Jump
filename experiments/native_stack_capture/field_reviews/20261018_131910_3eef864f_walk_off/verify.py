"""Offline review of one preserved failed owner window; no field capture entry points."""
import argparse,bisect,hashlib,importlib.util,json,pathlib,shutil,statistics,sys,tempfile
import numpy as np

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def module(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def review(root,raw,supplement):
 manifest=read(raw/'manifest.json');assert all(sha(raw/n.replace('\\','/'))==v['sha256'] for n,v in manifest.items())
 plan=read(raw/'frozen/field_plan01.json');record=read(raw/'run01/capture_record.json');m=read(raw/'formal/capture/measurement.json');report=read(raw/'formal/capture/report.json');state=read(raw/'formal/capture/state.json');post=read(supplement/'post_state01.json')
 assert record['plan_sha256']==sha(raw/'frozen/field_plan01.json')==sha(root/'experiments/gil_timestamped/field_plan01.json')
 baseline=read(root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];assert all(sha(root/n)==v for n,v in baseline.items())
 frozen=root/'experiments/single_usb_human_etw/frozen_sources.json';assert sha(frozen)==plan['formal_frozen_sha256']
 with tempfile.TemporaryDirectory() as temporary:
  stage=pathlib.Path(temporary);cap=stage/'runs'/pathlib.PureWindowsPath(record['formal_case']).name/'capture';cap.mkdir(parents=True)
  for p in (raw/'formal/capture').iterdir():shutil.copy2(p,cap/p.name)
  shutil.copy2(frozen,stage/'frozen_sources.json')
  integrity=module('integrity',root/'experiments/single_usb_human_etw/verify_trial.py').verify(cap)
 assert not post['production_mismatches'] and not post['formal_frozen_mismatches'] and not post['field_source_mismatches']
 assert post['field_fault_lock_retained'] and post['historical_failed_control_lock'] and not post['formal_lock']
 assert post['observer_sha256']==plan['observer_sha256'] and post['python_dll_sha256']==plan['python_dll_sha256']
 assert all(sha(raw/p)==v for p,v in plan['source_sha256'].items())
 sys.path.insert(0,str(root/'experiments/gil_timestamped'));from field import protocol
 sys.path.insert(0,str(root/'experiments/native_stack_capture'));from align_clock import mapping
 rows=[json.loads(x) for x in (raw/'run01/samples.jsonl').read_text().splitlines()];ss=rows[1:-1];assert len(ss)==120
 accepted=protocol(rows,m['pid'],120);assert not accepted and record['errors'] and not record.get('capture_stream_and_counters_complete') and not record['observer_still_running']
 clocks=record['anchors']+[t[k] for group in ('before','after') for t in record[group] for k in ('start','end')];clock=mapping(clocks);f=clock['qpc_frequency'];lo=clock['host_ns_offset_lower'];hi=clock['host_ns_offset_upper']
 assert rows[0]['qpc_frequency']==f
 bracket=lambda s:[s['qpc_begin']*10**9//f+lo,(s['qpc_end']*10**9+f-1)//f+hi]
 counters=[];native=read(raw/'formal/capture/native_cpu.json')
 for a,b in zip(record['before'],record['after']):
  assert (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and a['active'] and b['active']
  assert all(b[k]>=a[k] for k in ('user_100ns','kernel_100ns','cycles'))
  row=dict(pid=a['pid'],tid=a['tid'],role=a['role'],creation_100ns=a['creation_100ns'],cpu_s=(b['user_100ns']+b['kernel_100ns']-a['user_100ns']-a['kernel_100ns'])/1e7,cycles=b['cycles']-a['cycles'])
  if a['role']!='sdk':
   assert a['pid']==m['pid'] and a['tid']==record['formal_started']['tids'][a['role']]==native['start'][a['role']]['tid']==native['end'][a['role']]['tid']
   assert all(native['start'][a['role']][k]<=a[k]<=b[k]<=native['end'][a['role']][k] for k in ('user_100ns','kernel_100ns'))
   row['nested_within_independent_formal_GetThreadTimes']=True
  else:assert a['pid']!=m['pid']
  counters.append(row)
 with np.load(raw/'formal/capture/raw_frames.npz') as z:samples,receipts,bits=(z[k].copy() for k in ('sample_indices','received_ns','bits'))
 assert np.all(np.diff(samples)==1) and np.all(np.diff(receipts)>=0) and state['quality']['preflight']['bad_indices']==[576]
 bits[:,576]=0
 pubs=[x for x in report['walking_summary']['event_publications'] if x.get('active')];first=min(x['touch_sample'] for x in pubs);last=max(x['touch_sample'] for x in pubs)
 # The main raw passage block is bounded by >100-sample clear gaps. Retain the rule; sparse pulses outside it remain raw evidence.
 active=np.flatnonzero(bits.any(axis=1));groups=np.split(active,np.flatnonzero(np.diff(active)>100)+1);group=next(g for g in groups if samples[g[0]]<=first<=last<=samples[g[-1]])
 passage=[int(samples[group[0]]),int(samples[group[-1]])];receipt=lambda s:int(receipts[np.searchsorted(samples,s)])
 points=sorted(m['queue_common']+[m['queue_final']],key=lambda x:x[0]);times=[x[0] for x in points]
 assert all(b[1]>=a[1] and b[5]>=a[5] for a,b in zip(points,points[1:]));assert len(m['readers_at_start'])==1
 # The frozen source has one consumer, no nested event loop in drain, normal pops <=20. Arm precedes the marker and finish follows all reads.
 source=(root/'ui/session_controller.py').read_text();assert 'range(min(20, len(self._pending)))' in source
 assert record['formal_started']['armed_ns']==m['armed_ns'] and record['external_end_ns']<m['stop_request_ns']
 completion=lambda s:(next(i for i,p in enumerate(points) if p[1]>=s))
 footprints=[]
 for pub in pubs:
  s=pub['touch_sample'];published=pub['published_sample'];paint=m['paints'][str(pub['contact_id'])];i=completion(published);lower=points[i-1][0];upper=points[i][0];assert points[i-1][1]<published<=points[i][1] and lower<=paint
  footprints.append(dict(contact_id=pub['contact_id'],touch_sample=s,published_sample=published,receipt_formal_s=(receipt(s)-m['armed_ns'])/1e9,receipt_to_paint_ms=(paint-receipt(s))/1e6,publication_processing_bracket_formal_s=[(lower-m['armed_ns'])/1e9,(upper-m['armed_ns'])/1e9],receipt_to_publication_processing_bounds_ms=[(lower-receipt(s))/1e6,(upper-receipt(s))/1e6],publication_to_paint_bounds_ms=[max(0,(paint-upper)/1e6),(paint-lower)/1e6]))
 observations=[];failures=[]
 for i,s in enumerate(ss):
  b,e=bracket(s);assert record['external_begin_ns']<=b<=e<=record['external_end_ns']
  assert s['ordinal']==i and s['pid']==m['pid'] and (i==0 or ss[i-1]['qpc_end']<=s['qpc_begin'])
  owners=[t for t in s['traces'] if t['owns_gil']];assert len(owners)<=1
  if owners and not owners[0]['frames']:failures.append(dict(ordinal=i,tid=owners[0]['os_thread_id'],read_bracket_host_ns=[b,e],reason='GIL owner has no Python frames; unchanged whole-stream protocol rejects capture'))
  left=points[bisect.bisect_right(times,b)-1];right=points[bisect.bisect_left(times,e)]
  pending_lower=max(0,left[5]-right[1]-20)
  processed_range=[left[1]+1,right[1]];within=passage[0]<=processed_range[0]<=processed_range[1]<=passage[1]
  owner=owners[0] if owners else None
  observations.append(dict(ordinal=i,read_bracket_host_ns=[b,e],formal_bracket_s=[(b-m['armed_ns'])/1e9,(e-m['armed_ns'])/1e9],read_us=(s['qpc_end']-s['qpc_begin'])*1e6/f,bounding_completion_rows=[left,right],pending_lower_bound=pending_lower,possible_consumer_samples=processed_range,whole_bracket_in_main_passage=within,owner_tid=owner['os_thread_id'] if owner else None,owner_frames=owner['frames'] if owner else [],globally_accepted=False))
 assert [x['ordinal'] for x in failures]==[31]
 widths=[x['read_us'] for x in observations];gaps=[(b['qpc_begin']-a['qpc_begin'])*1e6/f for a,b in zip(ss,ss[1:])]
 # Select concrete recorded paths within proven backlog, without promoting a failed stream or counting time shares.
 candidates={}
 for o in observations:
  if o['pending_lower_bound']<=100 or not o['whole_bracket_in_main_passage'] or not o['owner_frames']:continue
  t=o['owner_tid'];role=next((k for k,v in record['formal_started']['tids'].items() if v==t),'other_same_process')
  key=(role,o['owner_frames'][0]['filename'],o['owner_frames'][0]['name'])
  candidates.setdefault(key,dict(ordinal=o['ordinal'],role=role,tid=t,formal_bracket_s=o['formal_bracket_s'],pending_lower_bound=o['pending_lower_bound'],frames=o['owner_frames'],evidence='Provisional record in failed stream; hypothesis only, no accepted field-holder attribution'))
 core_points=[p for p in m['queue_common']+m['queue_samples'] if receipt(passage[0])<=p[0]<=points[completion(passage[1])][0]]
 pose=[];snapshots=[dict(host_ns=m['armed_ns'],visual=m['visual_start'])]+m['telemetry']+[dict(host_ns=m['stop_request_ns'],visual=m['visual_end'])]
 for a,b in zip(snapshots,snapshots[1:]):
  if b['host_ns']>receipt(passage[0]) and a['host_ns']<receipt(passage[1]):pose.append(dict(formal_s=[(a['host_ns']-m['armed_ns'])/1e9,(b['host_ns']-m['armed_ns'])/1e9],valid_pose_draws=b['visual']['valid_pose_draws']-a['visual']['valid_pose_draws']))
 result=dict(case=pathlib.PureWindowsPath(record['formal_case']).name,scope='Offline review only; no new capture, production changes, or threshold changes.',integrity=integrity,controller=read(raw/'formal/controller_result.json'),stream=dict(expected=120,observed=120,protocol_pass=accepted,failures=failures,empty_owner_ordinals=[i for i,s in enumerate(ss) if not any(t['owns_gil'] for t in s['traces'])],error_rows=[x for x in rows if x['kind']=='error'],clock=clock,read_us=dict(min=min(widths),median=statistics.median(widths),max=max(widths)),actual_start_gap_us=dict(min=min(gaps),median=statistics.median(gaps),max=max(gaps)),formal_window_s=[observations[0]['formal_bracket_s'][0],observations[-1]['formal_bracket_s'][1]],init_ms=(rows[0]['qpc_end']-rows[0]['qpc_begin'])*1000/f,process_exited=True,fault_lock_retained=True),main_raw_passage=dict(samples=passage,receipt_formal_s=[(receipt(s)-m['armed_ns'])/1e9 for s in passage],window_metrics=module('window',root/'experiments/single_usb_field/analyze.py').window(sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0]),receipt(passage[0]),receipt(passage[1])+1),group_rule='Raw usable-bit block containing all 11 published contacts; split on >100-sample active-index gap, mask576 only in analysis. Sparse pulses outside preserved, not interpreted as steps.',pending_max_observed=max(p[3] for p in core_points),pose_intervals=pose,pose_draws_in_every_interval=all(p['valid_pose_draws']>0 for p in pose)),footprints=footprints,retained_thread_counters=counters,provisional_candidates=list(candidates.values()),observations=observations,post_state=post,actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,limits=['One owner-without-stack record fails whole-stream gate. All120 reads, nine no-owner states, failures, logs and locks retained; no accepted subset or replacement sampling.','Full-read brackets plus clock uncertainty are used; no sample-index/weight/midpoint timing. Bounds subtract maximum20 inflight frames and use only completion queue_common/queue_final.','Frozen single consumer normal drain<=20; no acquisition issues, drop, counter gaps, reentry path or arm/finish in observation window. queue_samples are only instantaneous witnesses.','Python frames are candidate interrupted boundaries; C/native internals, GIL hold duration, wait duration, time shares and dominant cause remain unknown. No simultaneous CSwitch in this round.','Different human input and historical CPU/wait profiles are observational comparisons; actual-load perturbation still unqualified.','GUI PID4308 and SDK PID7192 are separate. SDK counters are not SDK Python stacks or GUI GIL ownership.','Receipt starts after Python USB read/assembly; delay excludes unknown upstream age and is not physical-action-to-screen latency.','Other same-process owner candidate threads have trace-reported native IDs only, without retained independent lifetime handles; treat their identities as provisional.',
'Screen recording sparse frames93..102s have no common QPC anchor. Pose telemetry supports only interval draw presence, not uninterrupted correct tracking.'])
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,required=True);p.add_argument('--raw',type=pathlib.Path,required=True);p.add_argument('--supplement',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();r=review(a.root,a.raw,a.supplement)
 with a.output.open('x') as f:json.dump(r,f,ensure_ascii=False,indent=2);f.write('\n')
 print(json.dumps({k:r[k] for k in ['case','stream','main_raw_passage','footprints']},indent=2))
 print('Candidate paths',len(r['provisional_candidates']))
