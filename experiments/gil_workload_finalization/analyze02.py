"""Same preserved failed protocol case: FIFO timing and unmatched-payload ambiguity."""
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE));from verify import read,sha
sys.path.insert(0,str(ROOT/'experiments/gil_observation_termination'));from queue_bounds import bound_deque
sys.path.insert(0,str(ROOT/'experiments/gil_gui_analysis'));from temporal_review02 import event_bounds


if __name__=='__main__':
    import numpy as np
    scope=read(HERE/'analysis_scope02.json');raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert sha(raw/'manifest.json')==scope['raw_manifest_sha256'] and all(sha(raw/n)==v for n,v in manifest.items())
    assert sha(Path(__file__))==scope['reviewer_sha256']
    p=raw/'runs/protocol01/capture';m=read(p/'measurement.json');w=read(p/'workload_final.json');first=read(p/'application_return.json');final=read(p/'finalization.json');report=read(p/'report.json');official=read(HERE/'result01.json')
    with np.load(p/'raw_frames.npz') as data:
        indices=data['sample_indices'];assert np.array_equal(indices,np.arange(int(indices[0]),int(indices[-1])+1));received={int(n):int(t) for n,t in zip(indices,data['received_ns'])}
    bounds=bound_deque(sorted([[x[0],x[5],x[3]] for x in m['queue_common']+m['queue_samples']]),int(indices[0]),int(indices[-1]))
    mapping=read(ROOT/'experiments/gil_gui_analysis/publication_map02.json');assert sha(ROOT/'experiments/gil_gui_analysis/publication_map02.json')==scope['trigger_map_sha256']
    triggers={x['event']['event_id']:x for x in mapping['trigger_events']};events=event_bounds(m,report,received,triggers)
    worst=max(events,key=lambda x:x['source_touch_to_paint_ms'])
    canon=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))
    send=defaultdict(list);recv=defaultdict(list)
    for x in w['rows']['relay_packets']:send[canon(x['packet'])].append(x)
    for x in w['rows']['sdk_events']:
        if x['data']['event']=='pose_input':recv[canon(x['data']['packet'])].append(x)
    groups=[]
    for key in set(send)|set(recv):
        s,r=send[key],recv[key]
        if len(s)!=len(r):
            groups.append(dict(projected_payload=json.loads(key),send_count=len(s),receive_count=len(r),sender_arm_relative_s=[(x['observed_ns']-m['armed_ns'])/1e9 for x in s],receiver_host_arm_relative_s=[(x['observed_ns']-m['armed_ns'])/1e9 for x in r],candidate_unreceived_sender_occurrences=len(s),
                               interpretation='Identical payloads have no wire occurrence ID. Greedy FIFO leaves a final sender unmatched, but the missing occurrence is not uniquely located; preserve the entire candidate group.'))
    start=m['armed_ns']+12*10**9;end=start+5*10**9
    inf=[x for x in w['rows']['inferences'] if x['record']['inference_start_s']*1e9<=end and x['record']['inference_end_s']*1e9>=start]
    spans=[(x['record']['inference_end_s']-x['record']['inference_start_s'])*1000 for x in inf]
    result=dict(title='新协议失败窗口：严重队列积压重现，原返回状态保留，消息身份仍有歧义',
                official_protocol_qualification_pass=official['protocol_qualification_pass'],official_failed_checks=[k for k,v in official['checks'].items() if not v],
                full_original_report_state_input_exact=True,queue_bounds=bounds,worst_publication_event=worst,all_publication_event_bounds=events,
                application_return_model_confirmed=final['application_return_model_confirmed'],observer_tail_model_complete=all(final['observer_tail_model_checks'].values()),
                close_scope_wall_ms=[dict(begin_arm_s=(x['begin_ns']-m['armed_ns'])/1e9,end_arm_s=(x['end_ns']-m['armed_ns'])/1e9,wall_ms=(x['end_ns']-x['begin_ns'])/1e6) for x in w['rows']['model_close']],
                original_return_preserved=official['original_return_not_rewritten'],
                saved_counts=dict(submit=len(w['rows']['service_submit_calls']),inference=len(w['rows']['inferences']),ROI_inference=len(inf),relay=len(w['rows']['relay_packets']),SDK_input=sum(len(x) for x in recv.values())),
                ROI_API_wall_ms=dict(median=statistics.median(spans),max=max(spans)),unbalanced_metadata_payload_groups=groups,
                qualification_limits=['New metadata copy/lock/retention and post-return observer tail differ from earlier observer configurations. This is not a controlled performance A/B or evidence that observation caused no backlog.',
                                      'Per-event native roots were not collected in this case. No CPU/GIL/Qt percentage, primary responsible function or hold duration is inferred.',
                                      'No exact claim that a particular pre-arm sender was dropped. RuntimeNone can ignore inputs in the unchanged SDK source, but this run has no unique receiver-stage marker proving that branch for a specific occurrence.',
                                      'SDK global identity/clock acceptance remains failed; no endpoint or unmatched group was removed to make it pass.',
                                      'Model close interval is after the walk-processing ROI, includes waits/scheduling, and is not a cause proved for its earlier backlog.'],
                next_work=['Resolve projected-payload occurrence ambiguity using synthetic command/pose interleaving before any new acquisition; preserve this whole failure and all candidate occurrences.',
                           'Use this severe fixed-input record for source/batch/contact/pending temporal analysis; do not use it as an unperturbed GIL-holder witness.',
                           'Actual-load3%/1% perturbation, independent natural owner association and primary root remain incomplete. No new human Walk is currently needed.'],
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,root_cause_or_fix_complete=False)
    with (HERE/'review02.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:result[k] for k in ('official_failed_checks','queue_bounds','worst_publication_event','application_return_model_confirmed','observer_tail_model_complete','saved_counts','ROI_API_wall_ms')},indent=2))
