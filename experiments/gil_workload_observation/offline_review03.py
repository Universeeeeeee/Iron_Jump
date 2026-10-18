"""Expand the same failed02 window offline; never promote its failed acceptance."""
from collections import Counter,defaultdict,deque
import json
from pathlib import Path
import statistics
import sys
from verify import read,sha,canonical,infkey,check_workload,semantic_check

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]


def describe(values):
    return dict(count=len(values),min=min(values),median=statistics.median(values),max=max(values)) if values else dict(count=0)


if __name__=='__main__':
    plan=read(HERE/'analysis_plan03.json');raw=HERE/'runs/evidence02';ref=ROOT/plan['reference_capture']
    assert sha(Path(__file__))==plan['reviewer_sha256'] and sha(HERE/'verify.py')==plan['helper_sha256']
    assert sha(raw/'manifest.json')==plan['raw_manifest_sha256']
    manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    folder=raw/'runs/observation02/off_a';counter=read(folder/'record01.json');m=semantic_check(folder/'capture',ref);w=read(folder/'capture/workload01.json')
    details=check_workload(w,m,counter);rows=w['rows'];start,end=details['ROI_host_ns'];armed=m['armed_ns']
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from align_clock import mapping
    clock=mapping(w['anchors']+counter['anchors']+[x[k] for part in ('before','after') for x in counter[part] for k in ('start','end')])
    roi=[x for x in rows['inferences'] if x['record']['inference_start_s']*1e9<=end and x['record']['inference_end_s']*1e9>=start]
    services={x['service'] for x in roi}
    coverage={str(tag):dict(first_saved_begin_ns=min(x['record']['inference_start_s']*1e9 for x in rows['inferences'] if x['service']==tag),last_saved_end_ns=max(x['record']['inference_end_s']*1e9 for x in rows['inferences'] if x['service']==tag)) for tag in services}
    for c in coverage.values():c['saved_completions_bracket_ROI']=c['first_saved_begin_ns']<start and c['last_saved_end_ns']>end
    cadence=[];reference=[]
    for tag in range(w['service_count']):
        selected=[x for x in rows['inferences'] if x['service']==tag];times=[round(x['record']['frame_timestamp_s']*1000) for x in selected]
        cadence.extend(b-a for a,b in zip(times,times[1:]))
        last=None;ids=[]
        for x in rows['service_submit_calls']:
            if x['service']!=tag:continue
            stamp=round(x['captured_at_s']*1000)
            if last is None or stamp-last>=50:
                last=stamp;ids.append(x['metadata']['frame_index'])
        actual=[x['record']['metadata']['frame_index'] for x in selected]
        reference.append(dict(service=tag,minimum_interval_only_reference_count=len(ids),saved_inference_count=len(actual),same_frame_sequence=ids==actual,
                              warning='Logical timestamp-only reference; ignores latest-only overwrites, worker scheduling, event-buffer pruning and unfinished/unsaved terminal calls. No endpoint removed to force equality.'))
    io={}
    for method in ('_read','_send_pose'):
        values=[x for x in rows['gui_io'] if x['method']==method and x['begin_ns']<=end and x['end_ns']>=start]
        io[method]=dict(wall_span_ms=describe([(x['end_ns']-x['begin_ns'])/1e6 for x in values]),
                       longest=[dict(begin_arm_s=(x['begin_ns']-armed)/1e9,end_arm_s=(x['end_ns']-armed)/1e9,span_ms=(x['end_ns']-x['begin_ns'])/1e6) for x in sorted(values,key=lambda x:x['end_ns']-x['begin_ns'],reverse=True)[:5]],
                       meaning='Inclusive original method + nested callbacks + observer wall span. Not exclusive CPU, GIL hold time or quantitative causal share.')
    relays=defaultdict(deque)
    for x in rows['relay_packets']:relays[canonical(x['packet'])].append(x)
    offset=details['child_clock']['host_minus_child_ns_bounds'];delays=[];updates=[]
    for x in rows['sdk_events']:
        if x['data']['event']!='pose_input':continue
        sent=relays[canonical(x['data']['packet'])].popleft();child=x['data']['received_at_s']*1e9
        delays.append([(child+o-sent['observed_ns'])/1e6 for o in offset])
        record=x['data']['packet']['update']['inference']
        if record is not None and record['metadata'] is not None:updates.append(infkey(record))
    sdk_delay=dict(packet_count=len(delays),maximum_latency_ms_bounds=[max(x[0] for x in delays),max(x[1] for x in delays)],median_latency_ms_bounds=[statistics.median(x[0] for x in delays),statistics.median(x[1] for x in delays)],
                   meaning='Parent relay metadata return to child pose_input received marker, causal clock bracket. Excludes any later mailbox/control delay; cannot be transferred to old slow runs.')
    repeated=Counter(updates)
    before={x['tid']:x for x in counter['before'] if x['pid']==w['pid']};after={x['tid']:x for x in counter['after'] if x['pid']==w['pid']}
    counter_exposure={}
    for tid in details['inference_native_tids']:
        b=before[tid];a=after[tid];inner=[b['end']['perf_after_ns'],a['start']['perf_before_ns']];outer=[b['start']['perf_before_ns'],a['end']['perf_after_ns']]
        complete=[x for x in rows['inferences'] if x['tid']==tid and inner[0]<=x['record']['inference_start_s']*1e9 and x['record']['inference_end_s']*1e9<=inner[1]]
        overlap=[x for x in rows['inferences'] if x['tid']==tid and x['record']['inference_start_s']*1e9<=outer[1] and x['record']['inference_end_s']*1e9>=outer[0]]
        counter_exposure[str(tid)]=dict(guaranteed_counter_interval_ns=inner,possible_counter_interval_ns=outer,saved_API_calls_fully_inside_inner=len(complete),saved_API_calls_overlapping_outer=len(overlap),
                                       note='Counter reads are bounded and not simultaneous across threads. Does not assign native-pool CPU to inference calls or normalize CPU by these counts.')
    with (HERE/'links03.json').open('x') as f:json.dump(details,f,indent=2)
    report=dict(title='失败窗口02的离线工作量边界：保存的调用链路可核对，结束与扰动验收仍失败',
        official_capture_pass=False,official_errors=counter['errors'],off_b_not_attempted=True,full_original_report_state_input_exact=True,
        failed_checks=[k for k,v in details['checks'].items() if not v],saved_row_checks=details['checks'],
        GUI_pid=w['pid'],SDK_pid=next(x['pid'] for x in counter['before'] if x['role']=='sdk'),threads=dict(m['threads'],inference=details['inference_native_tids']),
        saved_counts=dict(video_submits=len(m['video_indices']),service_submit_calls=details['service_submit_call_count'],completed_adapter_and_inference_rows=details['actual_inference_count'],SDK_pose_inputs=details['SDK_pose_input_count'],SDK_calls=details['SDK_call_count'],GUI_valid_pose_draws=m['pose_draws']['valid'],ROI_saved_inferences=len(roi)),
        model_closed_before_metadata_snapshot=False,running_services_at_snapshot=w['running_services'],
        scope_limits=['These are saved completed rows. In-flight/late terminal callbacks may be absent; do not treat374 as a certified whole-process exposure count.',
                      'The rows were serialized while the service was still alive. Complete-service/model-close gates stay failed; pipeline failure was not re-sampled or replaced.',
                      'No recorded close-entry marker or closing native stack. A later Clearcut network-timeout message does not identify the active worker location or prove the walking-backlog cause.'],
        model_open_relative_arm_s=[[(x['begin_ns']-armed)/1e9,(x['end_ns']-armed)/1e9] for x in rows['model_open']],
        model_ready_relative_arm_s=[(x['observed_ns']-armed)/1e9 for x in rows['service_status'] if x['status']=='ready'],
        minimum_inference_VIDEO_timestamp_spacing_ms=describe(cadence),cadence_reference=reference,
        recorded_ROI_api_wall_ms=describe([(x['record']['inference_end_s']-x['record']['inference_start_s'])*1000 for x in roi]),
        saved_completion_coverage=coverage,actual_inference_counter_exposure=counter_exposure,
        SDK_update_reuse=dict(records_with_inference=len(updates),unique_saved_inference_references=len(repeated),repeated_occurrences=sum(n-1 for n in repeated.values()),max_repeats=max(repeated.values())),
        SDK_clock=details['child_clock'],native_clock=clock,SDK_packet_latency=sdk_delay,GUI_IO_ROI=io,
        queue=dict(max_pending=max(x[3] for x in m['queue_samples']),ROI_max_pending=max(x[3] for x in m['queue_samples'] if start<=x[0]<=end),severe_backlog_reproduced=False),
        root_evidence=['740 video/service submissions,374 saved completed inference records,626 cached-pose draws and550 SDK packet receipts are distinct stages, not interchangeable workload counters.',
                       'Saved inference-to-adapter-to-submit links and every relay-to-SDK metadata occurrence match. SDK PID is separate; causal child clock interval contains zero.',
                       'Model-ready marker is before this12..17s ROI; the model-open interval itself does not overlap this ROI. This does not exclude lazy initialization or runtime native work.',
                       'Pending peaked at64 in this window. It cannot replace the preserved3391/1125-frame slow episodes or identify their holder. No new production optimization occurred.'],
        next_minimal_work=['Keep both failed plans/windows and abort status. No more captures to obtain a passing replacement.',
                           'First clarify metadata termination/snapshot consistency using synthetic delayed-close tests. Keep observer loops, source selection and production code unchanged.',
                           'Any future observation must use a fresh freeze and preserve whole-service failure separately from bounded saved-ROI facts. Actual-load3%/1% gates remain unchanged and failed.',
                           'After applicable qualification, obtain same-window natural pre-global consumer context plus separately justified owner association in severe fixed-input backlog; no current need for new human Walk.'],
        actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,root_cause_or_fix_complete=False,
        raw_archive_sha256=read(HERE/'transport02.json')['archive_sha256'],analysis_plan_sha256=sha(HERE/'analysis_plan03.json'))
    with (HERE/'review03.json').open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:report[k] for k in ('official_capture_pass','failed_checks','saved_counts','model_ready_relative_arm_s','minimum_inference_VIDEO_timestamp_spacing_ms','cadence_reference','recorded_ROI_api_wall_ms','SDK_update_reuse','SDK_packet_latency','GUI_IO_ROI','queue')},ensure_ascii=False,indent=2))
