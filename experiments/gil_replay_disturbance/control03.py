"""Three frozen OFF/ON observer pairs on one saved contact chain, no device access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from verify import case_result,pair_result


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
from atomic_io03 import write
def wait_file(p,child,seconds):
    deadline=time.monotonic()+seconds
    while not p.exists():
        if child.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Missing '+str(p))
        time.sleep(.002)
    return read(p)


def case(mode,folder,plan,args):
    folder.mkdir();record=dict(mode=mode,errors=[]);target=observer=counter=None;rows=[]
    try:
        from observe import Observer
        from winapi import anchor
        with (folder/'target.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(args.plan.parent/'target03.py'),'--root',plan['replay_root'],'--input',plan['input_root'],'--plan',str(args.plan),'--output',str(folder/'target')],stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,QT_API='pyside6',QT_QPA_PLATFORM='offscreen'))
        ready=record['ready']=wait_file(folder/'target/ready.json',target,45);assert ready['pid']==target.pid
        counter=Observer([dict(pid=target.pid,tid=ready['tid'],role='consumer',name='original_chain')])
        with (folder/'observer.log').open('xb') as log:
            if mode=='on':
                output=folder/'samples.jsonl';command=[str(args.tool),str(target.pid),str(ready['tid']),str(plan['count']),str(plan['period_ms']),'0',str(output)];record['command']=command
                observer=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,_NT_SYMBOL_PATH=plan['symbol_search_path']));record['observer_pid']=observer.pid;deadline=time.monotonic()+8
                while True:
                    data=output.read_bytes() if output.exists() else b''
                    if b'\n' in data:
                        record['init']=json.loads(data.split(b'\n')[0]);assert record['init']['kind']=='init' and record['init']['error'] is None;break
                    if observer.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Observer initialization; retain PID and lock')
                    time.sleep(.002)
            record['anchors']=[anchor()];record['before']=counter.snapshot()
            (folder/'target/go').touch(exist_ok=False)
            if mode=='on':
                Path(str(output)+'.go').touch(exist_ok=False);observer.wait(timeout=12);record['observer_returncode']=observer.returncode
                assert observer.returncode==0 and not (folder/'observer.log').read_bytes();rows=[json.loads(l) for l in output.read_text().splitlines()]
            roi=wait_file(folder/'target/roi.json',target,20);record['after']=counter.snapshot();record['anchors'].append(anchor());(folder/'target/finish').touch(exist_ok=False)
        target.wait(timeout=45);record['target_returncode']=target.returncode;assert target.returncode==0 and not (folder/'target.log').read_bytes()
        complete=read(folder/'target/complete.json')
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if counter is not None:counter.close()
        record['target_still_running']=target is not None and target.poll() is None;record['observer_still_running']=observer is not None and observer.poll() is None
        write(folder/'record.json',record)
    assert not record['errors'] and not record['target_still_running'] and not record['observer_still_running'],record
    result=case_result(record,roi,complete,rows,plan,Path(plan['replay_root']));write(folder/'analysis.json',result)
    print(json.dumps(dict(case=folder.name,case_pass=result['case_pass'],wall_ms=result['wall_ns']/1e6,checks=result['checks'])),flush=True)
    return result


def main(a):
    plan=read(a.plan);a.output.mkdir(exist_ok=False);lock=a.output.parent/'active.lock';lock.mkdir();record=dict(errors=[],pairs=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        def sources_ok():return all(sha(a.plan.parent/n)==h for n,h in plan['sources'].items()) and sha(a.tool)==plan['observer_sha256']
        assert sources_ok() and sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        sys.path.insert(0,plan['native_helpers']);qualified=read(a.plan.parent/'waiter_qualification02.json');assert qualified['deterministic_waiter_control_pass'] and sha(a.plan.parent/'waiter_qualification02.json')==plan['waiter_qualification_sha256']
        for i,order in enumerate(plan['orders'],1):
            cases={mode:case(mode,a.output/f'pair{i}_{mode}',plan,a) for mode in order};paired=pair_result(cases['off'],cases['on'],plan);record['pairs'].append(dict(pair=i,**paired));print(json.dumps(record['pairs'][-1]),flush=True)
        assert sources_ok();record['offline_contact_chain_perturbation_pass']=all(p['offline_contact_chain_pair_pass'] for p in record['pairs'])
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        record['lock_retained']=lock.exists();record['plan_sha256']=sha(a.plan);write(a.output/'result.json',record)
    return int(bool(record['errors']) or not record.get('offline_contact_chain_perturbation_pass',False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--tool',type=Path,required=True);p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
