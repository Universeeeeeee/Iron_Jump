"""Offline absolute throughput/latency bounds for an existing window; no intervention effect."""
from bisect import bisect_left
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/session_gui_vision'))
sys.path.insert(0,str(ROOT/'experiments/gil_observation_termination'))
sys.path.insert(0,str(ROOT/'experiments/gil_gui_analysis'))
from clocks import SourceClock
from queue_bounds import bound_deque
from temporal_review02 import validate_queue,event_bounds,host_bins,completion_bracket
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def scheduled_times(indices,original_receipts,checked,epochs):
    if len(indices)!=len(original_receipts) or not len(indices):raise ValueError('Source axes differ')
    if not np.array_equal(indices,np.arange(int(indices[0]),int(indices[-1])+1)):raise ValueError('Not contiguous original input')
    if np.any(np.diff(original_receipts)<0):raise ValueError('Original source time regressed')
    if not int(indices[0])<=checked<int(indices[-1]):raise ValueError('Missing arm boundary')
    clock=SourceClock('.')
    if len(epochs)!=2:raise ValueError('Both source epochs required')
    for e in epochs:clock.apply(e)
    if epochs[0]['original_start_ns']!=int(original_receipts[0]):raise ValueError('Historical media origin changed')
    # checked sample is emitted before arm/rebase; the next frame uses epoch2.
    return np.where(indices>checked,epochs[1]['anchor_ns'],epochs[0]['anchor_ns'])+(original_receipts-original_receipts[0])

def analyze(stage,original):
    actor=read(stage/'client/actor/result.json');gui=read(stage/'gui_result.json');report=read(stage/'client/actor/report.json')
    assert gui['complete'] and actor['complete'] and not gui['errors'] and not actor['errors']
    with np.load(stage/'client/actor/raw_frames.npz') as z:raw={k:z[k].copy() for k in z.files}
    indices=raw['sample_indices'];receipts=raw['received_ns'];checked=report['report_config_snapshot']['device']['checked_sample_index']
    with np.load(original) as z:
        take=np.searchsorted(z['sample_indices'],indices);assert np.array_equal(z['sample_indices'][take],indices)
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(z[key][take],raw[key])
        original_receipts=z['received_ns'][take].copy()
    due=scheduled_times(indices,original_receipts,checked,actor['source_clock_history']);late=(receipts-due)/1e6
    assert np.all(np.diff(receipts)>=0) and np.all(late>=0), 'Late-only saved Source was not delivered as declared'
    assert len(actor['armed'])==1
    m=dict(queue_common=actor['queue_common'],queue_samples=[],armed_ns=actor['armed'][0],paints=gui['paint_first_ns'],arrivals=[[int(a),int(b),int(c)] for a,b,c in zip(receipts,due,indices)])
    received={int(n):int(t) for n,t in zip(indices,receipts)}
    witnesses=validate_queue(m,received);queue=bound_deque([[r[0],r[5],r[3]] for r in m['queue_common']],int(indices[0]),int(indices[-1]))
    mapping=read(ROOT/'experiments/gil_gui_analysis/publication_map02.json');triggers={e['event']['event_id']:e for e in mapping['trigger_events']}
    contacts=event_bounds(m,report,received,triggers)
    for event in contacts:
        k=bisect_left(indices,event['touch_sample']);event['touch_input_lateness_ms']=float(late[k])
        event['scheduled_touch_to_paint_ms']=(gui['paint_first_ns'][str(event['contact_id'])]-int(due[k]))/1e6
    assert len(contacts)==len(gui['expected_active_publications'])==len(gui['painted_active_publications'])
    phases=[]
    for phase in read(ROOT/'experiments/gil_gui_calibration/phases.json')['walk']:
        a,b=phase['start'],phase['end'];before=completion_bracket(m['queue_common'],a-1);after=completion_bracket(m['queue_common'],b-1)
        duration=[max(0,after[0]-before[1])/1e9,(after[1]-before[0])/1e9];count=b-a
        phases.append(dict(**phase,frame_count=count,completion_progress_duration_s=duration,completion_progress_fps_bounds=[count/duration[1],None if duration[0]==0 else count/duration[0]],
            scope='Host progress including scheduled idle; not algorithm busy-service throughput or CPU time.'))
    formal=indices>checked;maximum=max(e['scheduled_touch_to_paint_ms'] for e in contacts)
    return dict(scope='Posthoc descriptive absolute bounds from one existing successful isolated-session window; no new capture, matched A/B or repeatability claim.',
        source_frames=len(indices),formal_frames=int(formal.sum()),actual_receipt_span_rate_fps=float((len(indices)-1)*1e9/(receipts[-1]-receipts[0])),
        max_formal_input_lateness_ms=float(late[formal].max()),queue=queue,queue_witness_crosscheck=witnesses,
        max_observed_oldest_pending_ms=max((r[0]-r[4])/1e6 if r[4] is not None else 0 for r in m['queue_common']),
        contacts=contacts,max_receipt_touch_to_paint_ms=max(e['source_touch_to_paint_ms'] for e in contacts),max_scheduled_touch_to_paint_ms=maximum,
        host_second_progress_bounds=host_bins(m,int(indices[-1])),phase_progress_bounds=phases,
        observed_within_legacy_absolute_limits=dict(scheduled_touch_at_most_250ms=maximum<=250,continuous_deque_upper_at_most_250=queue['continuous_deque_peak_upper_bound']<=250,formal_input_lateness_at_most_150ms=float(late[formal].max())<=150),
        frozen_performance_acceptance_pass=False,paired_effect_identified=False,actual_load_disturbance_pass=False,field_fix_verified=False,primary_root_identified=False,
        limits=['One finite saved-source window, not continuous human/USB qualification.','Sparse queue witnesses bound the entire deque under contiguous FIFO assumptions; pending excludes popped/inflight frames.','Source/receipt-to-paint measures include algorithm confirmation, IPC/GUI and waits; no CPU/GIL share follows.','The failed window01 remains failed and is not a comparator.','Legacy historical original windows were both fast and slow; no ratio or improvement is inferred against them.'])

if __name__=='__main__':
    plan=read(HERE/'analysis_plan01.json')
    assert all(sha(ROOT/n)==v for n,v in plan['bindings'].items())
    original=HERE/'runs/recorded_source01.npz';assert sha(original)==plan['original_input_sha256']
    archive=ROOT/'experiments/session_gui_vision/runs/evidence02';manifest=read(archive/'manifest02.json');assert all(sha(archive/n)==v for n,v in manifest.items())
    result=analyze(archive/'runs02',original)
    history=read(ROOT/'experiments/gui_qos_candidate/result02.json');result['historical_context']=dict(severe_original_windows=history['symptom_decision']['severe_defaults'],total_original_windows=4,prior_symptom_advance=history['symptom_decision']['advance'],matched_baseline_for_this_window=False)
    result['bindings']=plan['bindings'];result['original_input_sha256']=plan['original_input_sha256']
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ('source_frames','actual_receipt_span_rate_fps','max_formal_input_lateness_ms','queue','max_receipt_touch_to_paint_ms','max_scheduled_touch_to_paint_ms','observed_within_legacy_absolute_limits','frozen_performance_acceptance_pass')},indent=2))
