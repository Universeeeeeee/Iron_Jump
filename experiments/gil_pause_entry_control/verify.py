"""Reject natural-wait attribution when a native request starts after explicit pause."""
import json
from pathlib import Path, PureWindowsPath


def ordered(*values):return all(a<=b for a,b in zip(values,values[1:]))
def begin(row):return row['begin']['qpc_before']
def end(row):return row['end']['qpc_after']


def valid_symbols(modules):
    return all((not m['pdb_matched'] or (not m['pdb_unmatched'] and
                any(c['guid']==m['pdb_identity']['guid']==m['loaded_guid'] and
                    c['age']==m['pdb_identity']['age']==m['loaded_age'] for c in m['codeview']))) and
               all((a['symbol'] is None or a['pdb_matched']) and a['pdb_matched']==m['pdb_matched'] and
                   a['module_base']==m['base'] and a['module_offset']==a['address']-m['base'] and
                   0<=a['module_offset']<m['image_size'] for a in m['resolved']) for m in modules)


def inspect(record,rows,catalog,case):
    samples=[s for s in rows if s['kind']=='sample']
    if len(samples)!=1:return dict(passed=False,checks=dict(one_sample=False))
    s=samples[0];ready=record['ready'];owner=ready['tids']['owner'];waiter=ready['tids']['waiter']
    modules={m['base']:m for m in catalog['modules']}
    addresses={a['address']:a for m in modules.values() for a in m['resolved']}
    native={n['tid']:n for n in s['native']}
    def symbols(n):return [addresses.get(f['address'],{}).get('symbol') for f in n['frames']]
    def roots(n):
        return (symbols(n)[-2:]==['BaseThreadInitThunk','RtlUserThreadStart'] and
                all(addresses.get(f['address'],{}).get('pdb_matched') for f in n['frames'][-2:]) and
                [PureWindowsPath(modules[f['module_base']]['path']).name.lower() for f in n['frames'][-2:]]==['kernel32.dll','ntdll.dll'])
    raw=(len(native)==len(s['native'])==2 and set(native)=={owner,waiter} and
         all(n['frames'] and n['context_ip']==n['frames'][0]['address'] and
             n['context_ip']>0 and 'frame cap' not in n['stopped_by'] for n in native.values()))
    wanted=('NtWaitForSingleObject','take_gil','PyGILState_Ensure')
    gil=(raw and all(n in symbols(native[waiter]) for n in wanted) and
         all(addresses[f['address']]['pdb_matched'] for f in native[waiter]['frames'] if addresses[f['address']]['symbol'] in wanted))
    observations=record['oracle'];labels={}
    for p in observations:labels.setdefault(p['label'],[]).append(p)
    pre=labels['before_intervention'][0];v=pre['values']
    p=labels['before_snapshot'][0];q=labels['after_snapshot'][0]
    owner_py=[t for t in s['traces'] if t['owns_gil']]
    counters=record['before'];after=record['after']
    checks=dict(
        stream=len(rows)==3 and rows[0]['kind']=='init' and rows[0]['schema']==4 and rows[0]['error'] is None and rows[-1]['kind']=='complete' and rows[-1]['samples_written']==1 and s['ordinal']==0 and all(r['pid']==ready['pid'] for r in rows),
        order=ordered(rows[0]['qpc_end'],begin(pre),end(pre),begin(p),end(p),s['qpc_begin'],s['suspended_qpc'],s['resume_returned_qpc'],s['qpc_end'],s['resolve_begin_qpc'],s['resolve_end_qpc'],rows[-1]['qpc'],begin(q),end(q)),
        no_request_before_intervention=v[0]==pre['confirm'] and v[0]%2==0 and v[1]==1 and v[2]==owner and v[4]==v[5]==v[8]==0,
        symbol_identities=valid_symbols(catalog['modules']),
        raw_contexts=raw,both_roots_closed=raw and all(roots(n) for n in native.values()),
        owner_python=len(owner_py)==1 and owner_py[0]['pid']==ready['pid'] and owner_py[0]['os_thread_id']==owner and any(f['name']=='hold_native' for f in owner_py[0]['frames']),
        native_pause=s['oracle_reads'][1]['values']==s['oracle_reads'][2]['values'] and s['oracle_reads'][1]['values'][1:3]==[1,owner],
        stable_owner=all(x['values'][0]==x['confirm']==v[0] and x['values'][1:3]==[1,owner] for x in observations if begin(x)>=begin(pre)),
        identities=len(counters)==len(after)==3 and {t['tid'] for t in counters}==set(ready['tids'].values()) and all(a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and a['pid']==ready['pid'] and all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns')) for a,b in zip(counters,after)),
        clean=not record['errors'] and record['observer_returncode']==record['target_returncode']==0 and not record['observer_still_running'] and not record['target_still_running'] and not record['owner_pause_outstanding'] and record['lock_retained'],
    )
    if case=='baseline01':
        checks.update(no_forced_pause='suspend' not in record and 'resume' not in record,
                      no_GIL_request=all(x['values'][4]==x['values'][5]==x['values'][8]==0 for x in observations if begin(x)>=begin(pre)),
                      no_GIL_chain=not gil and raw and not any(n in symbols(native[waiter]) for n in ('take_gil','PyGILState_Ensure')),
                      recovered=record['complete']['state'][4:6]==[0,0] and record['complete']['state'][11]==2)
    else:
        pause=record['suspend'];resume=record['resume'];delivery=labels['owner_pause_delivery'];before_request=labels['before_request'][0]
        checks.update(
            suspension_order=pause['previous']==0 and resume['previous']==1 and ordered(end(pre),pause['begin']['qpc_before'],pause['end']['qpc_after'],begin(delivery[0]),end(delivery[-1]),begin(before_request),end(before_request),record['request_gate_written']['qpc_before'],begin(p),end(q),resume['begin']['qpc_before']),
            delivered_owner_pause=len(delivery)==5 and len({x['values'][9] for x in delivery})==1 and delivery[-1]['values'][3]>delivery[0]['values'][3] and all(x['values'][4:6]==[0,0] and x['values'][8]==0 for x in delivery),
            request_after_pause=before_request['values'][4:6]==[0,0] and before_request['values'][8]==0 and all(x['values'][4:6]==[1,0] and x['values'][8]==1 for x in (p,q)),
            closed_induced_GIL_chain=gil,
            recovered=record['complete']['state'][4:6]==[1,1] and record['complete']['state'][11]==1,
        )
    return dict(case=case,checks=checks,passed=all(checks.values()),
                waiter_symbols=symbols(native[waiter]) if raw else [],
                natural_wait_before_explicit_intervention=False if checks['no_request_before_intervention'] else None,
                post_suspension_GIL_wait_chain=gil,
                scope='Explicit early-owner-pause synthetic counterexample, not reproduction of NtSuspendProcess internal ordering or actual application causality.')


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))


if __name__=='__main__':
    import argparse
    import hashlib
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('output',type=Path);a=parser.parse_args()
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    manifest=read(a.root/'manifest.json');assert all(sha(a.root/n)==h for n,h in manifest.items())
    plan=read(a.root/'plan01.json');assert all(sha(a.root/n)==h for n,h in plan['sources'].items())
    results=[]
    for name in plan['cases']:
        folder=a.root/'runs'/name;record=read(folder/'record.json');catalog=read(folder/'symbols.json')
        assert record['plan_sha256']==sha(a.root/'plan01.json')
        assert catalog['samples_sha256']==sha(folder/'samples.jsonl') and catalog['resolver_sha256']==plan['sources']['resolve_raw.py'] and catalog['dbghelp_sha256']==plan['dbghelp_sha256']
        assert not (folder/'observer.log').read_bytes() and not (folder/'target.log').read_bytes()
        results.append(inspect(record,[json.loads(l) for l in (folder/'samples.jsonl').read_text().splitlines()],catalog,name))
    result=dict(cases=results,explicit_early_owner_pause_mechanism_demonstrated=all(r['passed'] for r in results),
                exact_NtSuspendProcess_race_reproduced=False,actual_application_pause_artifact_proven=False,
                natural_wait_owner_association_qualified=False,actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,
                limitations=['One baseline and one separately frozen adversarial case; no rates, durations or false-positive percentages.',
                             'The original binary was unchanged. Extra owner-only suspension was an explicit external intervention, not observed internal NtSuspendProcess ordering.',
                             'No new application, human, optical/camera/USB, Run, or optimization AB window. Old failed windows and gates retained.'],
                plan_sha256=sha(a.root/'plan01.json'),manifest_sha256=sha(a.root/'manifest.json'))
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['explicit_early_owner_pause_mechanism_demonstrated'])
