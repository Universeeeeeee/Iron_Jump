"""Offline timing of this new protocol window; no CPU/GIL contribution inference."""
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))


if __name__=='__main__':
    import hashlib
    import numpy as np
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    scope=read(HERE/'analysis_scope01.json');raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json')
    assert sha(raw/'manifest.json')==scope['raw_manifest_sha256'] and all(sha(raw/n)==v for n,v in manifest.items())
    assert all(sha(ROOT/n)==v for n,v in scope['analysis_sources'].items())
    sys.path.insert(0,str(ROOT/'experiments/gil_observation_termination'));from queue_bounds import bound_deque
    sys.path.insert(0,str(ROOT/'experiments/gil_gui_analysis'));from temporal_review02 import event_bounds
    capture=raw/'runs/protocol01/capture';m=read(capture/'measurement.json');w=read(capture/'workload_final.json');final=read(capture/'finalization.json');report=read(capture/'report.json');official=read(HERE/'result01.json')
    with np.load(capture/'raw_frames.npz') as data:
        indices=data['sample_indices'];assert np.array_equal(indices,np.arange(int(indices[0]),int(indices[-1])+1))
        received={int(n):int(t) for n,t in zip(indices,data['received_ns'])}
    bounds=bound_deque(sorted([[x[0],x[5],x[3]] for x in m['queue_common']+m['queue_samples']]),int(indices[0]),int(indices[-1]))
    mapping=read(ROOT/'experiments/gil_gui_analysis/publication_map02.json');assert sha(ROOT/'experiments/gil_gui_analysis/publication_map02.json')==scope['trigger_map_sha256']
    triggers={x['event']['event_id']:x for x in mapping['trigger_events']};events=event_bounds(m,report,received,triggers)
    worst=max(events,key=lambda x:x['source_touch_to_paint_ms'])
    closes=[dict(begin_arm_s=(x['begin_ns']-m['armed_ns'])/1e9,end_arm_s=(x['end_ns']-m['armed_ns'])/1e9,wall_ms=(x['end_ns']-x['begin_ns'])/1e6) for x in w['rows']['model_close']]
    result=dict(title='真实SDK完整交付及旧协议验收通过；严重消费积压仍存在',
                protocol_qualification_pass=official['protocol_qualification_pass'],wire_delivery_pass=official['wire']['wire_delivery_pass'],legacy_workload_pass=official['legacy_workload']['observability_pass'],
                full_original_report_state_input_exact=True,queue_bounds=bounds,all_publication_event_bounds=events,worst_publication_event=worst,
                saved_counts=dict(service_submit=len(w['rows']['service_submit_calls']),inference=len(w['rows']['inferences']),ROI_inference=len(official['legacy_workload']['ROI_inference_identities']),relay=len(w['rows']['relay_packets']),**official['wire']['counts']),
                child_clock=official['wire']['child_clock'],native_clock=official['native_clock'],
                application_return_model_confirmed=final['application_return_model_confirmed'],observer_tail_model_complete=all(final['observer_tail_model_checks'].values()),model_close_wall_spans=closes,
                transport_recovery=dict(initial_SSH_completion_unconfirmed=True,recovered_same_task=True,restarted=False,target_exit_confirmed=True),
                limits=['This full-input replay has additional write hashing/hex retention and child Python hooks; actual-load disturbance remains unqualified.',
                        'Deque peak bounds require the unchanged finite contiguous frame-only source starting empty; they are not a blanket bound for live USB queues with issue entries.',
                        'Per-event timing bounds are correlated and are not additive causal costs. No CPU/GIL/Qt percentage or responsible holder is inferred.',
                        'Mailbox calls/normal returns are not business acceptance or physical SDK actuation.',
                        'New533/533 complete runtime delivery does not identify or repair old540/539 missing occurrence, and does not establish equivalence between different observer configurations.',
                        'Model close occurs after the12..17s ROI; its long wall interval is not a proved cause of the earlier walking backlog. Original-return unconfirmed status remains preserved.'],
                next='Now that one actual full transcript passes, freeze workload-qualified OFF/OFF variance followed by OFF/ON disturbance checks with unchanged3%/1% gates; retain failures and common-observer cost limitations. No human Walk needed now.',
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,root_cause_or_fix_complete=False)
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:result[k] for k in ('protocol_qualification_pass','queue_bounds','worst_publication_event','saved_counts','model_close_wall_spans')},indent=2))
