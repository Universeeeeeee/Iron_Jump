"""Join exact event IDs and the packet lineage used by first overview paint."""
import argparse,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('matrix',type=Path);a=p.parse_args();plan=json.loads((a.matrix/'plan.json').read_text());clock=json.loads((a.matrix/'clock.json').read_text());cases=[]
for folder in sorted(x for x in a.matrix.iterdir() if x.is_dir()):
 result=json.loads((folder/'result.json').read_text());assert result['complete'] and all(result['summary_equal'].values())
 case=dict(case=folder.name,mode=result['mode'],trace=result['trace'],report_equal=True,recognized_steps=result['recognized_steps'],valid_steps=result['valid_steps'],valid_cycles=result['valid_cycles'],run_wall_s=(result['finished_ns']-result['started_ns'])/1e9,parent_cpu_s=result['parent_cpu_ns']/1e9)
 if not result['trace']:cases.append(case);continue
 traces=[json.loads(f.read_text()) for f in folder.glob('trace_*.json')];rows=sorted([row for t in traces for row in t['rows']],key=lambda row:row['ns'])
 def one(stage,event,sequence='any'):
  matches=[x for x in rows if x['stage']==stage and event in x['events'] and (sequence=='any' or x['sequence']==sequence)]
  assert matches,(folder.name,stage,event,sequence)
  return matches[0]
 consumed=sorted([x for x in rows if x['stage']=='consumer_complete'],key=lambda row:row['sample']);assert len(consumed)==11
 events=[]
 for n,c in enumerate(consumed,1):
  event=c['events'][0];source=one('source_received',event);paint=one('paint_complete',event);seq=paint['sequence'];assert seq is not None
  receive=one('main_receive',event,seq);dispatch=one('gui_dispatch',event,seq)
  assert dispatch['pid']==paint['pid'] and dispatch['tid']==paint['tid'],'GUI dispatch/paint thread mismatch'
  if result['mode']!='process40':assert receive['tid']==paint['tid'],'Local receipt marker is not at GUI entry'
  stamp=dict(source_nominal=source['nominal_ns'],source_received=source['ns'],consumer_complete=c['ns'],child_send_begin=None,child_send_return=None,main_receive=receive['ns'],gui_dispatch=dispatch['ns'],paint_complete=paint['ns'])
  intervals=dict(source_nominal_phase_offset=(stamp['source_received']-stamp['source_nominal'])/1e6,input_to_consumer=(stamp['consumer_complete']-stamp['source_received'])/1e6,receive_to_dispatch=(stamp['gui_dispatch']-stamp['main_receive'])/1e6,dispatch_to_paint=(stamp['paint_complete']-stamp['gui_dispatch'])/1e6)
  if result['mode']=='process40':
   send=one('child_send_begin',event,seq);returned=one('child_send_return',event,seq);stamp.update(child_send_begin=send['ns'],child_send_return=returned['ns']);intervals.update(consumer_to_send=(stamp['child_send_begin']-stamp['consumer_complete'])/1e6,send_to_receive=(stamp['main_receive']-stamp['child_send_begin'])/1e6)
  else:intervals.update(consumer_to_receive=(stamp['main_receive']-stamp['consumer_complete'])/1e6)
  assert all(v>=-clock['bound_width_ns']/1e6 for key,v in intervals.items() if key!='source_nominal_phase_offset'),(folder.name,event,intervals)
  intervals['nominal_to_paint']=(stamp['paint_complete']-stamp['source_nominal'])/1e6
  events.append(dict(recognized_count=n,event_id=event,published_sample=c['sample'],paint_source_packet=seq,timestamps_ns=stamp,intervals_ms=intervals,child_send_missing_reason=None if result['mode']=='process40' else 'not_applicable_local_path'))
 first,last=events[0],events[-1];device=(last['published_sample']-first['published_sample'])/1000
 progress={stage:((last['timestamps_ns'][stage]-first['timestamps_ns'][stage])/1e9-device)*1000 for stage in ('source_received','consumer_complete','main_receive','gui_dispatch','paint_complete')}
 segment_growth={key:last['intervals_ms'][key]-first['intervals_ms'][key] for key in first['intervals_ms'] if key!='nominal_to_paint'}
 assert abs(sum(segment_growth.values())-progress['paint_complete'])<.001
 case.update(events=events,device_progress_s=device,progress_growth_ms=progress,segment_growth_ms=segment_growth,interval_summary_ms={key:dict(median=statistics.median(e['intervals_ms'][key] for e in events),maximum=max(e['intervals_ms'][key] for e in events)) for key in events[0]['intervals_ms']},observer_direct_extra_ms=sum(t['observer_extra_ns'] for t in traces)/1e6)
 cases.append(case)
summary=dict(source_report_sha256=plan['source_report_sha256'],source_exports_sha256=plan['source_exports_sha256'],production_head=plan['head'],cases=cases,clock_bound_width_us=clock['bound_width_ns']/1000,limits=['Qt paintEvent completion is not DWM/display presentation.','Camera, MediaPipe and SDK were disabled. Replay emits decoded SensorFrames, bypassing native USB reads and wire packet parsing. Source timing is reconstructed at nominal 1000Hz in 20-frame chunks; original receive timing and packetization are unavailable.','The signed source nominal phase offset includes 20-frame chunk-start pacing: frames later in a chunk can arrive up to 19ms before their per-frame nominal time. It is not a causal wait. Growth across events remains measurable; real USB delivery timing was not retained.','Measured observer execution cost is not an OFF/ON A/A perturbation-equivalence certificate. No CPU/GIL percentages are inferred.','One OFF/ON run per backend is a bounded observer control, not a statistical performance comparison.'])
(a.matrix/'analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
for case in cases:
 if case['trace']:print(case['case'],'growth_ms',case['progress_growth_ms'],'segments',case['segment_growth_ms'],'max_ms',{k:round(v['maximum'],3) for k,v in case['interval_summary_ms'].items()})
