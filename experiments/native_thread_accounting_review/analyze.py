"""Disaggregate retained native thread counters without rewriting failed protocols."""
import hashlib,json,sys
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'experiments/gil_gui_analysis'))
from temporal_review02 import completed_at
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def role(pid,tid,gui_pid,named):
    if pid!=gui_pid:return 'sdk_child'
    matched=[name for name,t in named.items() if t==tid]
    if len(matched)>1:raise ValueError('Conflicting observed thread identities')
    return matched[0] if matched else 'unassigned_same_process'

def analyze(archive,relative,workload,original_acceptance):
    manifest=read(archive/'manifest.json');assert all(sha(archive/n)==v for n,v in manifest.items())
    folder=archive/relative;r=read(folder/'record01.json');m=read(folder/'capture/measurement.json');w=read(folder/'capture'/workload)
    pid=r['target_pid'];assert pid==r['armed']['pid']==w['pid']
    named=dict(gui_main=r['armed']['tids']['gui'],consumer_qt=r['armed']['tids']['consumer'],optical_replay_reader=r['armed']['tids']['reader'])
    model={v['tid'] for v in w['rows']['inferences']};submit={v['tid'] for v in w['rows']['service_submit_calls']}
    assert len(model)==len(submit)==1
    named.update(model_caller=next(iter(model)),saved_video_submitter=next(iter(submit)))
    assert len(set(named.values()))==len(named)
    before={(v['pid'],v['tid']):v for v in r['before']};after={(v['pid'],v['tid']):v for v in r['after']}
    assert len(before)==len(r['before'])==len(after)==len(r['after']) and set(before)==set(after)
    sdk={v['pid'] for v in r['before'] if v['role']=='sdk'};assert len(sdk)==1 and pid not in sdk
    assert {v['pid'] for v in r['before']}=={pid}|sdk
    rows=[];groups=defaultdict(lambda:dict(threads=0,user_cpu_ms=0,kernel_cpu_ms=0,cpu_ms=0,cycles=0))
    for key,a in before.items():
        b=after[key];assert a['active'] and b['active'] and a['creation_100ns']==b['creation_100ns']
        assert all(b[k]>=a[k] for k in ('kernel_100ns','user_100ns','cycles'))
        assert a['end']['perf_after_ns']<=b['start']['perf_before_ns']
        kind=role(*key,pid,named);user=(b['user_100ns']-a['user_100ns'])/10000;kernel=(b['kernel_100ns']-a['kernel_100ns'])/10000
        row=dict(pid=key[0],tid=key[1],creation_100ns=a['creation_100ns'],original_role=a['role'],original_name=a.get('name'),observed_role=kind,
            user_cpu_ms=user,kernel_cpu_ms=kernel,cpu_ms=user+kernel,cycles=b['cycles']-a['cycles'],
            common_wall_ns_bounds=[b['start']['perf_before_ns']-a['end']['perf_after_ns'],b['end']['perf_after_ns']-a['start']['perf_before_ns']],
            native_module_attribution=None,native_stack_for_this_same_window_available=False)
        rows.append(row);g=groups[kind];g['threads']+=1
        for k in ('user_cpu_ms','kernel_cpu_ms','cpu_ms','cycles'):g[k]+=row[k]
    for name,tid in named.items():assert (pid,tid) in before
    interior=[max(a['end']['perf_after_ns'] for a in before.values()),min(b['start']['perf_before_ns'] for b in after.values())];assert interior[0]<interior[1]
    q=m['queue_common'];start=completed_at(q,interior[0],q[-1][1]);end=completed_at(q,interior[1],q[-1][1]);assert start is not None and end is not None
    model_calls=[v for v in w['rows']['adapter_calls'] if interior[0]<=v['begin_ns']<=v['end_ns']<=interior[1]]
    return dict(pid=pid,sdk_pid=next(iter(sdk)),original_record_errors=r['errors'],original_record_protocol_case_pass=r.get('protocol_case_pass'),original_archived_acceptance=original_acceptance,
        acceptance_not_reclassified=True,native_lifetimes_and_monotonic_pair_checks_pass=True,named_threads=named,groups=dict(groups),
        thread_rows=sorted(rows,key=lambda v:(v['pid'],-v['cpu_ms'],v['tid'])),
        observed_thread_cpu_sum_ms=dict(main_process=sum(v['cpu_ms'] for v in rows if v['pid']==pid),sdk_child=sum(v['cpu_ms'] for v in rows if v['pid']!=pid)),
        counter_common_interior_ns=interior,counter_common_interior_seconds=(interior[1]-interior[0])/1e9,
        consumer_completed_prefix_start_bounds=start,consumer_completed_prefix_end_bounds=end,consumer_progress_inside_common_interior_bounds=[max(0,end[0]-start[1]),max(0,end[1]-start[0])],
        queue_observed_peak_in_common_interior=max((v[3] for v in q if interior[0]<=v[0]<=interior[1]),default=None),whole_saved_window_observed_peak=max(v[3] for v in q),
        model_calls_fully_inside_common_interior=len(model_calls),
        bindings=dict(manifest_sha256=sha(archive/'manifest.json'),record_sha256=sha(folder/'record01.json'),workload_sha256=sha(folder/'capture'/workload)))
if __name__=='__main__':
    plan=read(HERE/'plan01.json');assert all(sha(ROOT/n)==v for n,v in plan['bindings'].items())
    cases={}
    for item in plan['cases']:cases[item['id']]=analyze(ROOT/item['archive'],item['relative'],item['workload'],read(ROOT/item['original_acceptance']))
    result=dict(cases=cases,scope='Offline retained thread-endpoint accounting in two historical windows. Original failed observability/protocol decisions are retained, not repaired.',
        findings=['Raw gui_native_* is process membership, not GUIpaint attribution.','Inferred model-caller and saved-video-submitter TIDs are independently separated from GUI main, consumer and optical replay reader.','Unassigned same-process threads remain unassigned; no native module is inferred from IDs orCPUamount.','SDK counters stay in their separatePID/GIL, not merged into GUI-process ownership.'],
        limits=['Each thread has its own endpoint brackets; sums are observed retained-threadCPU, not an atomic whole-process counter orCPUshare.','Threads born after target enumeration are not covered; endpoint enumeration cannot prove complete dynamic thread coverage.','No matching same-window native worker stacks/modules are saved in these two counter archives. Do not borrow anotherPID/TID/window stack.','Replay reader/video are experimental saved-source paths, not formal USB/camera threads.','No root percentage, native hot function, GHz, old3%/1% orstackqualification pass follows.'],new_capture=False,primary_root_identified=False,field_fix_verified=False,bindings=plan['bindings'])
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({n:dict(groups=c['groups'],consumer_progress_bounds=c['consumer_progress_inside_common_interior_bounds'],queue_peak=c['queue_observed_peak_in_common_interior'],seconds=c['counter_common_interior_seconds']) for n,c in cases.items()},indent=2))
