"""Recompute one coherent Python/native synthetic control, never a field capture."""
import argparse
import bisect
import hashlib
import json
from pathlib import Path,PureWindowsPath
import statistics
import sys


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def inspect(record,rows,plan,resolved,root):
    sys.path.insert(0,str(root/'experiments/native_stack_capture'));from align_clock import mapping
    clock=mapping(record['anchors']+[t[k] for g in ('before','after') for t in record[g] for k in ('start','end')]);f=clock['qpc_frequency']
    lo,hi=clock['host_ns_offset_lower'],clock['host_ns_offset_upper'];samples=[r for r in rows if r['kind']=='sample']
    oracle=[p for p in record['oracle'] if p[2]==p[6] and p[2]%2==0];starts=[p[0] for p in oracle];ends=[p[1] for p in oracle]
    modules={m['base']:m for m in resolved['modules']};addresses={r['address']:r for m in modules.values() for r in m['resolved']}
    lookup=lambda a:addresses.get(a,{})
    def names(native):return [lookup(f['address']).get('symbol') for f in native['frames']]
    def closed(native):
        n=names(native)
        return len(n)>=2 and [PureWindowsPath(modules[f['module_base']]['path']).name.lower() for f in native['frames'][-2:]]==['kernel32.dll','ntdll.dll'] and n[-2:]==['BaseThreadInitThunk','RtlUserThreadStart'] and all(lookup(f['address']).get('pdb_matched') for f in native['frames'][-2:])
    joins=[];unknown=[];native_checks=[];read_us=[];pause_us=[]
    previous=rows[0]['qpc_end'];ordered=True
    for i,s in enumerate(samples):
        b=s['qpc_begin']*10**9//f+lo;e=(s['qpc_end']*10**9+f-1)//f+hi
        ordered &= s['ordinal']==i and s['pid']==record['ready']['pid'] and previous<=s['qpc_begin']<=s['suspended_qpc']<=s['resume_returned_qpc']<=s['qpc_end']<=s['resolve_begin_qpc']<=s['resolve_end_qpc'];previous=s['resolve_end_qpc']
        read_us.append((s['qpc_end']-s['qpc_begin'])*1e6/f);pause_us.append((s['resume_returned_qpc']-s['suspended_qpc'])*1e6/f)
        assert record['external_begin_ns']<=b<=e<=record['external_end_ns']
        before,after=bisect.bisect_right(ends,b)-1,bisect.bisect_left(starts,e)
        if before<0 or after>=len(oracle):unknown.append(i);continue
        p,q=oracle[before],oracle[after]
        if p[2]!=q[2] or p[3]!=1 or p[3:5]!=q[3:5]:unknown.append(i);continue
        owners=[t for t in s['traces'] if t['owns_gil']];tids=record['ready']['tids'];native={n['tid']:n for n in s['native']}
        expected=tids['native'];waiter=tids['heartbeat'];owner=native.get(expected);waiting=native.get(waiter)
        identity=len(owners)==1 and owners[0]['pid']==record['ready']['pid'] and owners[0]['os_thread_id']==expected==p[4] and owners[0]['frames']==[]
        requested_py=[t for t in s['traces'] if t['os_thread_id']==waiter]
        python_waiter=len(requested_py)==1 and not requested_py[0]['owns_gil'] and any(f['name']=='heartbeat' for f in requested_py[0]['frames'])
        raw_ok=len(native)==len(s['native'])==2 and owner is not None and waiting is not None and all(n['frames'] and n['context_ip']==n['frames'][0]['address'] and n['context_ip']>0 and 'frame cap' not in n['stopped_by'] for n in native.values())
        roots=raw_ok and all(closed(n) for n in native.values())
        owner_path=raw_ok and 'NtDelayExecution' in names(owner) and 'SleepEx' in names(owner) and any(modules.get(f['module_base'],{}).get('image_sha256')==plan['oracle_dll_sha256'] for f in owner['frames'])
        wait_path=raw_ok and all(n in names(waiting) for n in ('NtWaitForSingleObject','take_gil','PyEval_RestoreThread')) and all(lookup(f['address']).get('pdb_matched') for f in waiting['frames'] if lookup(f['address']).get('symbol') in ('take_gil','PyEval_RestoreThread','NtWaitForSingleObject'))
        row=dict(ordinal=i,read_bracket_host_ns=[b,e],oracle_before=p,oracle_after=q,owner_identity_and_empty_python=identity,python_waiter=python_waiter,raw_context_ips_preserved=raw_ok,both_native_roots_closed=roots,owner_native_sleep_path=owner_path,waiter_closed_GIL_wait_path=wait_path)
        joins.append(row);native_checks.append(all(row[k] for k in ('owner_identity_and_empty_python','python_waiter','raw_context_ips_preserved','both_native_roots_closed','owner_native_sleep_path','waiter_closed_GIL_wait_path')))
    held=[p for p in oracle if p[3]==1]
    checks=dict(symbol_resolution_consistent=all((a['symbol'] is None or a['pdb_matched']) and a['pdb_matched']==m['pdb_matched'] and a['module_base']==m['base'] and a['module_offset']==a['address']-m['base'] and 0<=a['module_offset']<m['image_size'] for m in modules.values() for a in m['resolved']),stream_complete=len(samples)==plan['count'] and len(rows)==len(samples)+2 and rows[0]['kind']=='init' and rows[0]['schema']==2 and rows[0]['error'] is None and rows[0]['qpc_frequency']==f and rows[0]['pid']==record['ready']['pid'] and rows[-1]['kind']=='complete' and rows[-1]['samples_written']==len(samples) and rows[-1]['pid']==record['ready']['pid'],ordered=ordered and previous<=rows[-1]['qpc'],
        clock=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'],eligible_floor=len(joins)>=plan['eligible_floor'],every_eligible_matches=bool(native_checks) and all(native_checks),
        same_epoch_stable=all(p[2]<=q[2] and (p[2]!=q[2] or p[3:5]==q[3:5]) for p,q in zip(oracle,oracle[1:])),held_heartbeat_still=bool(held) and len({p[5] for p in held})==1,recovered=record['complete']['completed'] and record['complete']['heartbeat']>held[-1][5] and record['complete']['host_ns']>record['external_end_ns'],
        native_lifetimes=all(a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns')) for a,b in zip(record['before'],record['after'])),activity_flags_not_interpreted=rows[0]['activity_flags_valid'] is False and all(s['activity_flags_valid'] is False for s in samples),clean=not record['errors'] and record['observer_returncode']==record['target_returncode']==0 and not record['observer_still_running'] and not record['target_still_running'])
    gaps=[(b['qpc_begin']-a['qpc_begin'])*1e3/f for a,b in zip(samples,samples[1:])]
    stats=lambda v:dict(min=min(v),median=statistics.median(v),max=max(v)) if v else None
    return dict(checks=checks,coherent_native_control_pass=all(checks.values()),samples=len(samples),eligible=len(joins),unknown=unknown,joins=joins,clock=clock,full_read_us=stats(read_us),successful_suspend_return_to_resume_return_us=stats(pause_us),actual_start_gap_ms=stats(gaps),unresolved_modules=[dict(path=m['path'],sha256=m['image_sha256'],raw_RVAs=[a['module_offset'] for a in m['resolved']]) for m in modules.values() if not m['pdb_matched']],actual_load_disturbance_pass=False,changing_owners_and_python_frames_validated=False,field_attribution_ready=False,root_cause_or_fix_complete=False,limits=['One new constant native-oracle synthetic control. Does not identify historical field owners or their cost.','Raw initial context IP and duplicate initial StackWalk frame are both retained. StackWalk64 ending is accepted as a closed root only with independently matched root symbols.','Unmatched NativeOwner.dll frame remains module+RVA. No arbitrary function name or kernel stack is fabricated.','Activity flags were read under suspension and cannot describe Running/Ready/Waiting.','Successful suspend-return to resume-return bracket includes instrumentation work; it is not GIL hold time or a calibrated total target pause. Suspend begins before its return marker.','No CPU/CSwitch ETW gate changed. Dynamic-owner correctness and under-load disturbance remain unqualified.'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--resolved',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items());plan=read(a.raw/'plan01.json');record=read(a.raw/'run01/record.json');assert sha(a.raw/'plan01.json')==record['plan_sha256'] and sha(a.raw/'target/release/ironjump-gil-coherent-native.exe')==plan['observer_sha256']
    assert all(sha(a.raw/n)==h for n,h in plan['sources'].items()) and not (a.raw/'run01/observer.log').read_bytes()
    resolved=read(a.resolved);assert resolved['samples_sha256']==sha(a.raw/'run01/samples.jsonl')
    rows=[json.loads(s) for s in (a.raw/'run01/samples.jsonl').read_text().splitlines()];result=inspect(record,rows,plan,resolved,a.root)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='joins'},indent=2))
