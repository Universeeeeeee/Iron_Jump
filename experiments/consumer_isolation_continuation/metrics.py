"""Same absolute endpoints for both saved-source backends; no GIL/CPU shares."""
import json
from pathlib import Path
import statistics
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
for p in ('session_isolation_throughput','gil_gui_analysis','gil_observation_termination'):sys.path.insert(0,str(ROOT/'experiments'/p))
from analyze01 import scheduled_times
from temporal_review02 import validate_queue,event_bounds
from queue_bounds import bound_deque
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
def measure(stage,original):
    stage=Path(stage);a=read(stage/'client/actor/result.json');g=read(stage/'gui_result.json');report=read(stage/'client/actor/report.json');work=read(stage/'workload_final.json')
    assert a['complete'] and g['complete'] and not a['errors'] and not g['errors']
    with np.load(stage/'client/actor/raw_frames.npz') as z:raw={k:z[k].copy() for k in z.files}
    idx=raw['sample_indices'];receipts=raw['received_ns'];checked=report['report_config_snapshot']['device']['checked_sample_index']
    with np.load(original) as z:
        take=np.searchsorted(z['sample_indices'],idx);assert np.array_equal(z['sample_indices'][take],idx)
        for k in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(z[k][take],raw[k])
        original_receipts=z['received_ns'][take].copy()
    due=scheduled_times(idx,original_receipts,checked,a['source_clock_history']);late=(receipts-due)/1e6;assert np.all(late>=0) and np.all(np.diff(receipts)>=0)
    m=dict(queue_common=a['queue_common'],queue_samples=[],armed_ns=a['armed'][0],paints=g['paint_first_ns']);received={int(n):int(t) for n,t in zip(idx,receipts)}
    checks=validate_queue(m,received);queue=bound_deque([[r[0],r[5],r[3]] for r in m['queue_common']],int(idx[0]),int(idx[-1]))
    triggers={v['event']['event_id']:v for v in read(ROOT/'experiments/gil_gui_analysis/publication_map02.json')['trigger_events']};events=event_bounds(m,report,received,triggers)
    for e in events:
        i=int(np.searchsorted(idx,e['touch_sample']));e['scheduled_touch_to_paint_ms']=(g['paint_first_ns'][str(e['contact_id'])]-int(due[i]))/1e6
    cost=[(v['record']['inference_end_s']-v['record']['inference_start_s'])*1000 for v in work['rows']['inferences']]
    first_touch=min(e['touch_sample'] for e in events);first_touch_due=int(due[int(np.searchsorted(idx,first_touch))])
    before=[(v['record']['inference_end_s']-v['record']['inference_start_s'])*1000 for v in work['rows']['inferences'] if v['record']['inference_end_s']*1e9<first_touch_due]
    return dict(backend=g['backend'],raw_frames=len(idx),queue=queue,queue_crosscheck=checks,contacts=events,max_latency_ms=max(e['source_touch_to_paint_ms'] for e in events),scheduled_max_ms=max(e['scheduled_touch_to_paint_ms'] for e in events),input_lateness_ms=float(late[idx>checked].max()),observed_queue_lower=queue['combined_observed_deque_peak_lower_bound'],queue_upper=queue['continuous_deque_peak_upper_bound'],
        work=dict(video=len(g['video_frame_ids']),inferences=len(cost),model_wall_ms_median=statistics.median(cost),model_wall_ms_mean=statistics.mean(cost),precontact_model_calls=len(before),precontact_model_wall_ms_median=statistics.median(before) if before else None,sdk=g['sdk'],draws=g['draws']),
        context=read(stage/'pipeline_review.json')['runtime_context'],original_return_model_confirmed=read(stage/'finalization.json')['application_return_model_confirmed'])
