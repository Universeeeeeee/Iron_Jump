"""Derive retained severe-window consumer capacity and required margin."""
import hashlib,json,statistics
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'));sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def interval(actor,first_sample,last_sample,limit=250):
 rows=actor['queue_common'];start=next(r for r in rows if r[5]>=first_sample);end=next(r for r in rows if r[5]>=last_sample);duration=(end[0]-start[0])/1e9
 arrived=end[5]-start[5];completed=end[1]-start[1];arrival=arrived/duration;service=completed/duration;allowed=max(0,limit-start[3]);required=(arrived-allowed)/duration
 return dict(first_touch_sample=first_sample,last_release_sample=last_sample,duration_s=duration,start_pending=start[3],end_pending=end[3],arrived_frames=arrived,completed_frames=completed,
  arrival_fps=arrival,effective_service_fps=service,queue_growth_fps=(end[3]-start[3])/duration,effective_ms_per_frame=1000/service,
  required_fps_for_250=required,required_ms_per_frame_for_250=1000/required,required_throughput_increase_for_250=required/service-1,
  required_throughput_increase_for_zero_growth=arrival/service-1)
if __name__=='__main__':
 cold=read(ROOT/'experiments/cold_boot_vision_process_ab/evidence/two_window_result03.json');chain=read(ROOT/'experiments/walk_compute_offline_diagnosis/chain_summary01.json')
 actors={name:read(HERE/'evidence'/f'{name}_actor.json') for name in ('cold01_process','cold02_original')};derived={name:interval(value,60188,64957) for name,value in actors.items()}
 contact=[trial['phases']['contact_core']['wall_us_per_input']['median'] for trial in chain['trials']]
 for name,value in derived.items():
  value['retained_peak_lower']=cold['cases'][name]['observed_queue_lower'];value['retained_peak_upper']=cold['cases'][name]['queue_upper'];value['scheduled_max_ms']=cold['cases'][name]['scheduled_max_ms']
  value['extra_effective_ms_above_offline_chain_range']=[value['effective_ms_per_frame']-max(contact)/1000,value['effective_ms_per_frame']-min(contact)/1000]
 process=derived['cold01_process']
 result=dict(conclusion='The immediate software root is insufficient worst-state consumer service capacity: arrivals remain about1000Hz while the consumer completes about797fps even after video/model isolation.',
  cases=derived,offline_contact_chain_median_us_range=[min(contact),max(contact)],
  minimum_gap_to_close=dict(process_cold_required_additional_fps=process['required_fps_for_250']-process['effective_service_fps'],process_cold_required_ms_reduction_per_frame=process['effective_ms_per_frame']-process['required_ms_per_frame_for_250']),
  localization=dict(excluded_as_sufficient_fix=['video decode and MediaPipe process isolation'],supported=['consumer/GUI-process execution and synchronization overhead beyond the offline algorithm chain','slow execution-delivery state affecting consumer capacity'],
    unknown=['share from GIL acquisition','share from Qt/event-loop batching','share from native computation/CPU delivery','exact responsible function']),
  next_candidate=dict(name='consumer session process isolation',reason='It is the remaining existing boundary that removes GUI-process GIL/Qt contention while preserving the original filter/Processor/report chain.',
    current_evidence='Semantic delivery already passed; severe-state performance has not been qualified.',required_gate='Must close at least the measured 160fps / 0.21ms-per-frame process-cold gap and meet <=250 frames and <=250ms with exact reports.'),
  no_new_capture=True,formal_fix_verified=False,field_fix_verified=False,
  bindings=dict(process_actor_sha256=sha(HERE/'evidence/cold01_process_actor.json'),original_actor_sha256=sha(HERE/'evidence/cold02_original_actor.json'),cold_result_sha256=sha(ROOT/'experiments/cold_boot_vision_process_ab/evidence/two_window_result03.json'),offline_chain_sha256=sha(ROOT/'experiments/walk_compute_offline_diagnosis/chain_summary01.json')))
 (HERE/'result01.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
