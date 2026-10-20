"""Acceptance analysis for one live consumer-process Walk."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def queue_bound(rows,first,last):
 if not rows or first>last:return False,None
 previous_e=previous_d=first-1;upper=0
 for row in rows:
  enqueued,pending=row[5],row[3];dequeued=enqueued-pending
  if not previous_e<=enqueued<=last or not previous_d<=dequeued<=enqueued or pending<0:return False,None
  upper=max(upper,enqueued-previous_d);previous_e,previous_d=enqueued,dequeued
 return previous_e==previous_d==last,upper
def analyze(folder):
 folder=Path(folder);parent=read(folder/'parent.json');actor=read(folder/'client/actor/result.json');report=read(folder/'client/actor/report.json');state=read(folder/'client/actor/state.json');acquisition=read(folder/'client/actor/acquisition.json')
 with np.load(folder/'client/actor/raw_frames.npz') as z:raw={name:z[name].copy() for name in z.files}
 indices=raw['sample_indices'];contiguous=bool(len(indices) and np.array_equal(indices,np.arange(int(indices[0]),int(indices[-1])+1)));rows=sorted(actor['queue_common']+actor['queue_samples']+([actor['queue_final']] if actor['queue_final'] else []),key=lambda row:row[0]);queue_valid,upper=queue_bound(rows,int(indices[0]),int(indices[-1]));queue_valid=queue_valid and contiguous and not acquisition['issues']
 receipts={int(sample):int(stamp) for sample,stamp in zip(indices,raw['received_ns'])};events=[]
 for event in report['walking_summary']['event_publications']:
  if not event['active']:continue
  key=str(event['contact_id']);paint=parent['paint_first_ns'].get(key);visual=parent['visual_first_receipt_ns'].get(key);touch=event['touch_sample'];received=receipts.get(touch)
  events.append(dict(contact_id=event['contact_id'],touch_sample=touch,published_sample=event['published_sample'],touch_in_raw=received is not None,paint_observed=paint is not None,visual_observed=visual is not None,receipt_to_visual_ms=None if visual is None or received is None else (visual-received)/1e6,receipt_to_paint_ms=None if paint is None or received is None else (paint-received)/1e6,visual_to_paint_ms=None if paint is None or visual is None else (paint-visual)/1e6))
 latencies=[event['receipt_to_paint_ms'] for event in events if event['receipt_to_paint_ms'] is not None];ages=[(row[0]-row[4])/1e6 for row in rows if row[4] is not None];device=report['report_config_snapshot']['device'];buffer=report['report_config_snapshot']['raw_buffer'];checked=device['checked_sample_index'];session=indices>checked;checked_receipt=receipts.get(checked);wire_exact=bool(np.array_equal(raw['bits'],1-np.unpackbits(raw['wire'],axis=1,bitorder='little')));archive_hash=hashlib.sha256(raw['bits'][session].tobytes()).hexdigest();stream_ids=np.unique(raw['stream_ids'])
 semantic=dict(raw_wire_bits_exact=wire_exact,acquisition_frame_count_matches=len(acquisition['frames'])==len(indices),report_stream_matches=len(stream_ids)==1 and device['stream_id']==stream_ids[0],quality_checked_time_matches=checked_receipt is not None and state['quality']['preflight']['checked_monotonic_ns']==checked_receipt,report_raw_buffer_matches=int(session.sum())==buffer['total_received_frames']==buffer['retained_frames'] and not buffer['truncated'] and buffer['raw_only_tail_frames']==0,raw_archive_hash_matches=archive_hash==state['raw_archive_sha256'],event_audit_matches=state['event_audit']==report['walking_summary']['event_audit'])
 accept=dict(parent_complete=parent['complete'],actor_complete=actor['complete'],camera_and_pose_load_valid=parent['visual']['valid_pose_draws']>0 and parent['record_stats']['frames_written']>0 and not parent['SDK_errors'],raw_contiguous=contiguous,no_input_issues=not acquisition['issues'],no_dropped_frames=int(raw['dropped_frames_before'].sum())==0,one_stream=len(stream_ids)==1,semantic_consistency=all(semantic.values()),queue_bound_valid=queue_valid,queue_upper_le_250=upper is not None and upper<=250,all_active_contacts_painted=bool(events) and len(latencies)==len(events),max_contact_to_paint_le_250=bool(latencies) and max(latencies)<=250,report_has_steps=bool(report['walking_summary']['steps']),cleanup_complete=not actor['readers_after_cleanup'] and not actor['output']['writer_alive'] and not actor['output']['pending_sequences'])
 result=dict(complete=all(accept.values()),acceptance=accept,semantic=semantic,queue=dict(observed_pending_peak=max((row[3] for row in rows),default=None),continuous_peak_upper_bound=upper,oldest_pending_age_ms_peak=max(ages,default=None)),events=events,max_contact_to_paint_ms=max(latencies,default=None),steps=len(report['walking_summary']['steps']),active_events=len(events),raw_frames=len(indices),report_sha256=hashlib.sha256((folder/'client/actor/report.json').read_bytes()).hexdigest(),limits=['Receipt-to-paint starts at host USB delivery of the touch sample; it includes consumer FIFO, algorithm publication, IPC and GUI paint. It is not a CPU/GIL share.','The continuous FIFO upper bound is accepted only for contiguous, issue-free input with a final empty witness.','Human-observed step count, lead foot and perceived latency remain an independent field acceptance input.'])
 (folder/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);value=analyze(parser.parse_args().folder);print(json.dumps(value,ensure_ascii=False));raise SystemExit(not value['complete'])
