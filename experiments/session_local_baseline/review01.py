"""Independent archive/values/roles plus descriptive baseline queue evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/session_gui_vision'));sys.path.insert(0,str(ROOT/'experiments/session_isolation_throughput'));sys.path.insert(0,str(HERE))
from pipeline_review import verify_pipeline
from analyze01 import scheduled_times
sys.path.insert(0,str(ROOT/'experiments/gil_gui_analysis'));sys.path.insert(0,str(ROOT/'experiments/gil_observation_termination'))
from temporal_review02 import validate_queue,event_bounds
from queue_bounds import bound_deque
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    archive=HERE/'runs/evidence01';manifest=read(archive/'manifest01.json');assert all(sha(archive/n)==v for n,v in manifest.items())
    stage=archive/'runs';work=read(stage/'workload_final.json');gui=read(stage/'gui_result.json');actor=read(stage/'client/actor/result.json');report=read(stage/'client/actor/report.json');context=read(stage/'gui_context.json')
    assert context['pid']==gui['pid'] and context['session_id']!=0 and context['priority_class']==16384 and context['qpa']=='windows'
    assert b'Traceback' not in (archive/'task01.stderr').read_bytes()
    result=verify_pipeline(stage,work['anchors']);assert result==read(stage/'pipeline_review.json')
    spec=importlib.util.spec_from_file_location('prior_values_review',ROOT/'experiments/session_gui_vision/review02.py');values=importlib.util.module_from_spec(spec);spec.loader.exec_module(values)
    result['full_semantic_comparison']=values.values(stage)
    original=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz';plan=read(HERE/'plan01.json');assert sha(original)==plan['input_sha256']['raw_frames.npz']
    with np.load(stage/'client/actor/raw_frames.npz') as z:raw={k:z[k].copy() for k in z.files}
    indices=raw['sample_indices'];receipts=raw['received_ns'];checked=report['report_config_snapshot']['device']['checked_sample_index']
    with np.load(original) as z:
        take=np.searchsorted(z['sample_indices'],indices);assert np.array_equal(z['sample_indices'][take],indices)
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(z[key][take],raw[key])
        original_receipts=z['received_ns'][take].copy()
    due=scheduled_times(indices,original_receipts,checked,actor['source_clock_history']);late=(receipts-due)/1e6;assert np.all(late>=0) and np.all(np.diff(receipts)>=0)
    received={int(n):int(t) for n,t in zip(indices,receipts)};m=dict(queue_common=actor['queue_common'],queue_samples=[],armed_ns=actor['armed'][0],paints=gui['paint_first_ns'])
    queue=bound_deque([[r[0],r[5],r[3]] for r in m['queue_common']],int(indices[0]),int(indices[-1]));checks=validate_queue(m,received)
    triggers={e['event']['event_id']:e for e in read(ROOT/'experiments/gil_gui_analysis/publication_map02.json')['trigger_events']};events=event_bounds(m,report,received,triggers)
    for event in events:
        i=int(np.searchsorted(indices,event['touch_sample']));event['scheduled_touch_to_paint_ms']=(gui['paint_first_ns'][str(event['contact_id'])]-int(due[i]))/1e6
    maximum=max(e['source_touch_to_paint_ms'] for e in events)
    result['descriptive_current_baseline']=dict(queue=queue,queue_crosscheck=checks,contacts=events,max_receipt_touch_to_paint_ms=maximum,max_scheduled_touch_to_paint_ms=max(e['scheduled_touch_to_paint_ms'] for e in events),max_formal_input_lateness_ms=float(late[indices>checked].max()),severe_baseline_observed=queue['combined_observed_deque_peak_lower_bound']>=1000 and maximum>=1000,
        matched_to_prior_isolated_window=False,intervention_effect_withheld=True)
    result.update(actual_interactive_session=context['session_id'],parent_priority_class=context['priority_class'],active_publication_ids_painted=gui['painted_active_publications'],original_ground_paint_calls=gui['original_paint_calls'],actual_overlay_draws=gui['draws'],actual_sdk_work=gui['sdk'],
        bindings=dict(plan_sha256=sha(HERE/'plan01.json'),archive_sha256=sha(HERE/'evidence01.zip'),review_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ('original_same_process_gui_delivery_pass','full_semantic_comparison','actual_model_calls','actual_video_frames')}))
    print(json.dumps(result['descriptive_current_baseline'],indent=2))
