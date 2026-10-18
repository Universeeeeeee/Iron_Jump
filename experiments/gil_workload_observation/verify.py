"""Metadata identity/clock/lifecycle gates, never CPU/GIL causal percentages."""
from collections import Counter,defaultdict,deque
import hashlib
import json
from pathlib import Path

read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
canonical=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))
def key(meta):return (meta['camera_clock_epoch'],meta['frame_index'])
def infkey(r):return (key(r['metadata']),r['frame_timestamp_s'],r['inference_end_s'])


def check_workload(w,m,counter):
    rows=w['rows'];checks={};errors=[]
    checks['capture_identity']=w['schema']==1 and w['pid']==counter['target_pid']==counter['armed']['pid'] and not w['running_services'] and w['replay_serialized']
    checks['no_callback_faults']=not rows['callback_errors']
    checks['complete_services']=w['service_count']>0 and all(any(x['service']==i and x['status']=='ready' for x in rows['service_status']) and any(x['service']==i and x['status']=='stopped' for x in rows['service_status']) for i in range(w['service_count']))
    checks['pipeline_health']=all(x['record']['error'] is None for x in rows['inferences']) and all(x['error'] is None for x in rows['adapter_calls']+rows['model_open']+rows['model_close']+rows['gui_io']) and all(x['is_open'] for x in rows['model_open']) and all(not x['is_open'] for x in rows['model_close']) and bool(rows['model_open']) and bool(rows['model_close'])
    checks['model_lifetimes']=({x['adapter'] for x in rows['model_open']}=={x['adapter'] for x in rows['model_close']} and all(any(o['adapter']==a['adapter'] and o['tid']==a['tid'] and o['end_ns']<=a['begin_ns'] for o in rows['model_open']) and any(c['adapter']==a['adapter'] and c['tid']==a['tid'] and a['end_ns']<=c['begin_ns'] for c in rows['model_close']) for a in rows['adapter_calls']))
    submits=defaultdict(list)
    for s in rows['service_submit_calls']:
        if s['metadata'] is not None:submits[(s['service'],key(s['metadata']))].append(s)
    adapters=defaultdict(list)
    for a in rows['adapter_calls']:adapters[(a['tid'],a['timestamp_ms'])].append(a)
    links=[];infos={}
    for r in rows['inferences']:
        info=r['record'];meta=info['metadata']
        if meta is None:errors.append('Inference without original metadata');continue
        candidates=submits.get((r['service'],key(meta)),[]);calls=adapters.get((r['tid'],round(info['frame_timestamp_s']*1000)),[])
        submit=[s for s in candidates if s['metadata']==meta and round(s['captured_at_s']*1000)/1000==info['frame_timestamp_s']]
        if len(submit)!=1 or len(calls)!=1:errors.append('Nonunique submit/adapter join');continue
        a=calls[0];s=submit[0]
        bounds=(s['begin_ns']<=a['begin_ns'] and info['inference_start_s']*1e9<=a['begin_ns']<=a['end_ns']<=info['inference_end_s']*1e9<=r['observed_ns'])
        same=a['has_pose']==info['has_pose'] and a['dtype']=='uint8' and len(a['shape'])==3 and a['shape'][2]==3
        links.append(dict(service=r['service'],tid=r['tid'],frame=meta['frame_index'],epoch=meta['camera_clock_epoch'],timestamp_s=info['frame_timestamp_s'],begin_s=info['inference_start_s'],end_s=info['inference_end_s'],shape=a['shape'],bounds=bounds,call_matches=same))
        k=infkey(info)
        if k in infos:errors.append('Duplicate inference identity')
        infos[k]=info
    checks['all_adapter_inference_submit_links']=bool(links) and len(links)==len(rows['inferences'])==len(rows['adapter_calls']) and not errors and all(x['bounds'] and x['call_matches'] for x in links)
    checks['GUI_roles']=all(x['tid']==m['threads']['gui'] for name in ('gui_io','relay_packets','sdk_events','control_lifecycle','tracking_requests') for x in rows[name])
    before=counter['before'];after=counter['after'];bmap={(x['pid'],x['tid']):x for x in before};amap={(x['pid'],x['tid']):x for x in after}
    checks['native_handle_identity']=len(bmap)==len(before)==len(amap)==len(after) and set(bmap)==set(amap) and all(x['active'] and amap[k]['active'] and x['creation_100ns']==amap[k]['creation_100ns'] and all(amap[k][f]>=x[f] for f in ('cycles','user_100ns','kernel_100ns')) for k,x in bmap.items())
    sdkpids={x['pid'] for x in before if x['role']=='sdk'}
    checks['separate_SDK_PID']=len(sdkpids)==1 and w['pid'] not in sdkpids and {x['pid'] for x in before if x['role']!='sdk'}=={w['pid']}
    started=[x for x in rows['control_lifecycle'] if x['event']=='started'];ended=[x for x in rows['control_lifecycle'] if x['event']=='finished']
    checks['control_lifecycle']=len(started)==len(ended)==1 and {x['pid'] for x in started}==sdkpids and started[0]['control']==ended[0]['control'] and ended[0]['exit_code']==0 and ended[0]['observed_ns']>started[0]['observed_ns']
    checks['SDK_control_identity']=len(started)==1 and all(x['control']==started[0]['control'] for x in rows['sdk_events'])
    roi=[counter['armed']['host_ns']+12000000000,counter['armed']['host_ns']+17000000000]
    role_tids={x['tid'] for x in rows['inferences'] if x['record']['inference_start_s']*1e9<=roi[1] and x['record']['inference_end_s']*1e9>=roi[0]}
    checks['inference_ROI_lifetimes']=bool(role_tids) and all((w['pid'],tid) in bmap and (w['pid'],tid) in amap and bmap[(w['pid'],tid)]['active'] and amap[(w['pid'],tid)]['active'] and bmap[(w['pid'],tid)]['creation_100ns']==amap[(w['pid'],tid)]['creation_100ns'] for tid in role_tids)
    pose=[x for x in rows['sdk_events'] if x['data']['event']=='pose_input'];calls=[x for x in rows['sdk_events'] if x['data']['event']=='sdk_call']
    checks['SDK_aggregate_counts']=(sum(x['data']['event']=='tracking_decision' and x['data']['reason']=='tracking' for x in rows['sdk_events'])==m['sdk']['tracking_decisions'] and sum(x['data']['method']=='set_speed' and any(x['data']['args']) for x in calls)==m['sdk']['nonzero_speeds'] and bool(pose) and bool(calls))
    queues=defaultdict(deque)
    for r in rows['relay_packets']:queues[canonical(r['packet'])].append(r)
    lower=[];upper=[];packet_links=0;missing=[]
    for r in pose:
        data=r['data'];q=queues.get(canonical(data['packet']))
        if not q:missing.append('SDK packet without unique prior relay occurrence');continue
        sent=q.popleft();lower.append(sent['observed_ns']-data['received_at_s']*1e9);upper.append(r['observed_ns']-data['received_at_s']*1e9);packet_links+=1
        for u in (data['packet']['barrier'],data['packet']['update']):
            if u is None or u['inference'] is None:continue
            info=u['inference']
            if info['metadata'] is None or infos.get(infkey(info))!=info:missing.append('SDK reference without exact inference metadata')
    for r in calls:upper.append(r['observed_ns']-r['data']['returned_at']*1e9)
    remaining=sum(len(q) for q in queues.values())
    checks['all_relay_SDK_metadata_links']=packet_links==len(pose)==len(rows['relay_packets']) and not missing and remaining==0
    clock=None
    if lower and upper:
        lo=max(lower);hi=min(upper);clock=dict(host_minus_child_ns_bounds=[lo,hi],uncertainty_ns=hi-lo,zero_offset_compatible=lo<=0<=hi)
    checks['independent_child_clock_bracket']=clock is not None and clock['zero_offset_compatible'] and checks['all_relay_SDK_metadata_links']
    # GimbalSdk.set_speed/disable_ai check the C return code then return None.
    # tracking_start/stop protocol acknowledgements separately carry result0.
    checks['SDK_calls_successful']=all(x['data']['method'] in ('set_speed','disable_ai') and x['data']['error'] is None and x['data']['result'] is None and x['data']['started_at']<=x['data']['returned_at'] for x in calls)
    return dict(checks=checks,observability_pass=all(checks.values()),errors=errors+missing,inference_links=links,
                actual_inference_count=len(rows['inferences']),service_submit_call_count=len(rows['service_submit_calls']),
                whole_inference_frame_ids=[x['frame'] for x in links],
                SDK_pose_input_count=len(pose),SDK_call_count=len(calls),child_clock=clock,ROI_host_ns=roi,
                ROI_inference_identities=[[x['epoch'],x['frame']] for x in links if x['begin_s']*1e9<=roi[1] and x['end_s']*1e9>=roi[0]],
                inference_native_tids=sorted(role_tids),
                limits=['Adapter/inference spans are wall intervals, not CPU time, GIL occupancy, or exclusive function cost.',
                        'Relay/SDK checks project metadata only; no pose coordinates or pixels are retained by these hooks. These are necessary workload links, not proof of identical complete execution.'])


def semantic_check(capture,reference):
    import copy
    import numpy as np
    m=read(capture/'measurement.json');prior=read(reference/'measurement.json')
    assert read(capture/'complete.json')['system_exit_code']==0 and m['baseline_hashes']==prior['baseline_hashes'] and m['sources']==prior['sources'] and m['renderer_sha256']==prior['renderer_sha256']
    assert not m['errors'] and not m['sdk_errors'] and m['sdk']['start_success'] and m['sdk']['stop_success'] and m['pose_draws']['valid']>0 and m['pose_draws']['disabled_calls']==0
    assert m['delivered_metadata_sha256']==prior['delivered_metadata_sha256'] and m['source_indices']==prior['source_indices']
    with np.load(capture/'raw_frames.npz') as new,np.load(reference/'raw_frames.npz') as old:
        assert all(np.array_equal(new[k],old[k]) for k in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'))
        receipt=new['received_ns'].copy();assert np.all(np.diff(receipt)>=0);checked=int(receipt[3500])
    report=read(capture/'report.json');old_report=read(reference/'report.json')
    for value in (report,old_report):
        for v in (value['report_config_snapshot']['device'],value['report_config_snapshot']['beam_quality']['preflight']):
            if value is report:assert v['checked_monotonic_ns']==checked
            del v['checked_monotonic_ns']
    assert report==old_report
    a=copy.deepcopy(m['state']);b=copy.deepcopy(prior['state']);assert a['quality']['preflight']['checked_monotonic_ns']==checked
    del a['quality']['preflight']['checked_monotonic_ns'];del b['quality']['preflight']['checked_monotonic_ns'];assert a==b
    return m


if __name__=='__main__':
    import argparse
    import sys
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('reference',type=Path);p.add_argument('output',type=Path);p.add_argument('--project',type=Path,required=True);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    plan=read(a.raw/'plan02.json');assert all(sha(a.raw/n)==v for n,v in plan['sources'].items())
    sys.path.insert(0,str(a.project/'experiments/native_stack_capture'));from align_clock import mapping
    status=read(a.raw/'runs/observation02/result01.json');assert status['plan_sha256']==sha(a.raw/'plan02.json')
    result=dict(cases={},actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    for name in plan['cases']:
        folder=a.raw/'runs/observation02'/name
        if not (folder/'record01.json').exists():result['cases'][name]=dict(observability_pass=False,not_attempted=True);continue
        r=read(folder/'record01.json');assert r['plan_sha256']==sha(a.raw/'plan02.json')
        if not r.get('case_pass'):result['cases'][name]=dict(observability_pass=False,capture_failed=True,errors=r['errors']);continue
        m=semantic_check(folder/'capture',a.reference);w=read(folder/'capture/workload01.json')
        assert w['sources']=={n:plan['sources'][n] for n in ('entry01.py','workload.py')}
        reviewed=check_workload(w,m,r);clock=mapping(w['anchors']+r['anchors']+[x[k] for group in ('before','after') for x in r[group] for k in ('start','end')])
        reviewed['native_clock']=clock;reviewed['checks']['native_clock_precision']=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max']
        reviewed['checks']['capture_clean']=not r['errors'] and not r['target_still_running'] and r['target_returncode']==0
        reviewed['observability_pass']=all(reviewed['checks'].values());reviewed['full_semantics_exact']=True
        reviewed['video_indices']=m['video_indices'];reviewed['max_pending']=max(x[3] for x in m['queue_samples']);reviewed['model_open_host_ns']=[[x['begin_ns'],x['end_ns']] for x in w['rows']['model_open']];reviewed['armed_ns']=m['armed_ns']
        result['cases'][name]=reviewed
    x,y=(result['cases'][n] for n in plan['cases'])
    result['all_observability_pass']=all(c['observability_pass'] for c in result['cases'].values()) and not status['errors'] and status.get('all_cases_complete',False)
    if x.get('full_semantics_exact') and y.get('full_semantics_exact'):
        result['pair']=dict(video_submit_identities_equal=x['video_indices']==y['video_indices'],whole_actual_inference_frame_ids_equal=x['whole_inference_frame_ids']==y['whole_inference_frame_ids'],ROI_actual_inference_frame_ids_equal=[z[1] for z in x['ROI_inference_identities']]==[z[1] for z in y['ROI_inference_identities']],ROI_inference_epoch_and_id_sequences_equal=x['ROI_inference_identities']==y['ROI_inference_identities'],whole_actual_inference_counts=[x['actual_inference_count'],y['actual_inference_count']],SDK_pose_inputs=[x['SDK_pose_input_count'],y['SDK_pose_input_count']],max_pending=[x['max_pending'],y['max_pending']])
    result['limits']=['One prospectively frozen OFF/OFF pair only; common metadata observer and old10Hz QueueProbe remain enabled. External stack sampler and ETW OFF. No statistical equivalence or zero overhead claim.',
                      'All failures and the earlier16-case cohorts remain. New metadata does not retrospectively reconstruct their inference choices, identify a causal owner, or replace3%/1% gates.']
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2));raise SystemExit(not result['all_observability_pass'])
