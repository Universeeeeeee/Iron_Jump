"""One frozen two-phase native GIL waiter control; no application entry points."""
import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import struct
import subprocess
import sys
import time


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
    with p.open('x') as f:json.dump(v,f,indent=2)
def wait_file(p,child,seconds):
    deadline=time.monotonic()+seconds
    while not p.exists():
        if child.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Missing '+str(p))
        time.sleep(.002)
    return read(p)


def main(a):
    plan=read(a.plan);a.output.mkdir(exist_ok=False);lock=a.output.parent/'active.lock';lock.mkdir()
    record=dict(errors=[],phases={},oracle=[],free_running_controls=[],field_attribution_ready=False);target=observer=counter=None
    try:
        assert all(sha(a.plan.parent/n)==h for n,h in plan['sources'].items())
        assert sha(a.tool)==plan['observer_sha256'] and sha(a.dll)==plan['oracle_dll_sha256']
        assert sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        sys.path.insert(0,plan['native_helpers']);from observe import Observer;from winapi import anchor
        with (a.output/'target.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(a.plan.parent/'fixture.py'),str(a.output/'target'),str(a.dll)],stdout=log,stderr=subprocess.STDOUT)
        ready=record['ready']=wait_file(a.output/'target/ready.json',target,8);assert ready['pid']==target.pid
        with (a.output/'target/oracle.bin').open('rb') as backing:
            shared=mmap.mmap(backing.fileno(),64,access=mmap.ACCESS_READ)
            try:
                def oracle():
                    b=time.perf_counter_ns();epoch,phase,owner,beat,requested,acquired,beat_tid,_=struct.unpack_from('<8Q',shared);confirm=struct.unpack_from('<Q',shared)[0];e=time.perf_counter_ns()
                    row=[b,e,epoch,phase,owner,beat,confirm,requested,acquired,beat_tid];record['oracle'].append(row);return row
                for _ in range(plan['free_running_count']):
                    first=oracle();time.sleep(plan['free_running_ms']/1000);record['free_running_controls'].append([first,oracle()])
                for phase in (1,2):
                    folder=a.output/f'phase{phase}';folder.mkdir();item=record['phases'][str(phase)]={}
                    tids={n:ready['tids'][n] for n in (str(phase),'waiter','native_beat')}
                    counter=Observer([dict(pid=target.pid,tid=t,role='consumer',name=n) for n,t in tids.items()])
                    item['before']=counter.snapshot();item['anchors']=[anchor()];output=folder/'samples.jsonl'
                    command=[str(a.tool),str(target.pid),str(tids['waiter']),str(plan['count_per_phase']),str(plan['period_ms']),str(ready['oracle_address']),str(output)];item['command']=command
                    with (folder/'observer.log').open('xb') as log:
                        observer=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,_NT_SYMBOL_PATH=plan['symbol_search_path']))
                        item['observer_pid']=observer.pid;deadline=time.monotonic()+8
                        while True:
                            data=output.read_bytes() if output.exists() else b''
                            if b'\n' in data:
                                item['init']=json.loads(data.split(b'\n')[0]);assert item['init']['kind']=='init' and item['init']['error'] is None;break
                            if observer.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Observer initialization; preserve PID and lock')
                            time.sleep(.002)
                        (a.output/f'target/go{phase}').touch(exist_ok=False);deadline=time.monotonic()+3
                        while True:
                            p=oracle()
                            if p[2]==p[6] and p[2]%2==0 and p[3]==p[7]==phase and p[8]<phase:break
                            if target.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Native GIL request phase missing')
                            time.sleep(.001)
                        time.sleep(plan['settle_ms']/1000);oracle();item['external_begin_ns']=time.perf_counter_ns();Path(str(output)+'.go').touch(exist_ok=False)
                        deadline=time.monotonic()+8
                        while observer.poll() is None:
                            oracle()
                            if time.monotonic()>deadline:raise TimeoutError('Observer pending; never kill during suspension')
                            time.sleep(.001)
                        oracle();item['external_end_ns']=time.perf_counter_ns();item['observer_returncode']=observer.returncode
                    item['after']=counter.snapshot();item['anchors'].append(anchor());counter.close();counter=None
                    assert observer.returncode==0 and not (folder/'observer.log').read_bytes()
                    item['done']=wait_file(a.output/f'target/done{phase}.json',target,6);oracle()
                target.wait(timeout=8);oracle()
            finally:shared.close()
        record['target_returncode']=target.returncode;record['complete']=read(a.output/'target/complete.json')
        assert target.returncode==0 and not (a.output/'target.log').read_bytes()
        assert all(sha(a.plan.parent/n)==h for n,h in plan['sources'].items()) and sha(a.tool)==plan['observer_sha256']
        record['capture_complete']=True
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if counter is not None:counter.close()
        record['observer_still_running']=observer is not None and observer.poll() is None;record['target_still_running']=target is not None and target.poll() is None
        record['plan_sha256']=sha(a.plan);record['lock_retained']=lock.exists();write(a.output/'record.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in ('oracle','phases','free_running_controls')},indent=2))
    return int(bool(record['errors']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--tool',type=Path,required=True);p.add_argument('--dll',type=Path,required=True);p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
