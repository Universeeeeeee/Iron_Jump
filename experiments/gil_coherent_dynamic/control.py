"""Single changing-owner window with independent native pause probes."""
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
    with p.open('x') as out:json.dump(v,out,indent=2)


def main(args):
    plan=read(args.plan);args.output.mkdir(exist_ok=False)
    lock=args.output.parent/'active.lock';lock.mkdir()
    record=dict(errors=[],oracle=[],field_attribution_ready=False);target=observer=counter=None
    try:
        assert all(sha(args.plan.parent/n)==h for n,h in plan['sources'].items())
        assert sha(args.tool)==plan['observer_sha256'] and sha(args.dll)==plan['oracle_dll_sha256']
        assert sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        sys.path.insert(0,plan['native_helpers']);from observe import Observer;from winapi import anchor
        with (args.output/'target.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(args.plan.parent/'fixture.py'),str(args.output/'target'),str(args.dll)],stdout=log,stderr=subprocess.STDOUT)
        record['target_pid']=target.pid;deadline=time.monotonic()+8
        while not (args.output/'target/ready.json').exists():
            if target.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Target not ready')
            time.sleep(.01)
        ready=record['ready']=read(args.output/'target/ready.json');assert ready['pid']==target.pid
        targets=[dict(pid=target.pid,tid=tid,role='consumer',name=name) for name,tid in ready['tids'].items()]
        counter=Observer(targets);record['before']=counter.snapshot();record['anchors']=[anchor()]
        with (args.output/'observer.log').open('xb') as log,(args.output/'target/oracle.bin').open('rb') as backing:
            shared=mmap.mmap(backing.fileno(),32,access=mmap.ACCESS_READ)
            try:
                def oracle():
                    b=time.perf_counter_ns();epoch,phase,tid,beat=struct.unpack_from('<QQQQ',shared);confirm=struct.unpack_from('<Q',shared)[0];e=time.perf_counter_ns()
                    row=[b,e,epoch,phase,tid,beat,confirm];record['oracle'].append(row);return row
                output=args.output/'samples.jsonl';record['init_launch_ns']=time.perf_counter_ns()
                record['free_running_controls']=[]
                for _ in range(plan['free_running_count']):
                    first=oracle();time.sleep(plan['free_running_ms']/1000);last=oracle()
                    record['free_running_controls'].append([first,last])
                command=[str(args.tool),str(target.pid),str(ready['tids']['heartbeat']),str(plan['count']),str(plan['period_ms']),str(ready['oracle_address']),str(output)]
                observer=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,_NT_SYMBOL_PATH=plan['symbol_search_path']))
                record['observer_pid']=observer.pid;record['command']=command;deadline=time.monotonic()+8
                while True:
                    data=output.read_bytes() if output.exists() else b''
                    if b'\n' in data:
                        record['init']=json.loads(data.split(b'\n')[0]);assert record['init']['kind']=='init' and record['init']['error'] is None;break
                    if observer.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Observer init pending; preserve live PID, no kill')
                    time.sleep(.005)
                (args.output/'target/go').touch(exist_ok=False);deadline=time.monotonic()+5
                while True:
                    p=oracle()
                    if p[2]==p[6] and p[2]%2==0 and p[3] in (1,2):break
                    if target.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Native phase not observed')
                    time.sleep(.001)
                time.sleep(.3);record['external_begin_ns']=time.perf_counter_ns();Path(str(output)+'.go').touch(exist_ok=False)
                deadline=time.monotonic()+10
                while observer.poll() is None:
                    oracle()
                    if time.monotonic()>deadline:raise TimeoutError('Observer pending; no force kill')
                    time.sleep(.001)
                oracle();record['external_end_ns']=time.perf_counter_ns();record['observer_returncode']=observer.returncode
                record['after']=counter.snapshot();record['anchors'].append(anchor());target.wait(timeout=10);oracle()
            finally:shared.close()
        record['target_returncode']=target.returncode;record['complete']=read(args.output/'target/complete.json')
        assert target.returncode==observer.returncode==0 and not (args.output/'observer.log').read_bytes()
        assert all(a['active'] and b['active'] and a['creation_100ns']==b['creation_100ns'] for a,b in zip(record['before'],record['after']))
        assert all(sha(args.plan.parent/n)==h for n,h in plan['sources'].items()) and sha(args.tool)==plan['observer_sha256']
        record['capture_complete']=True
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if counter is not None:counter.close()
        record['observer_still_running']=observer is not None and observer.poll() is None;record['target_still_running']=target is not None and target.poll() is None
        record['plan_sha256']=sha(args.plan);record['lock_retained_for_offline_validation']=lock.exists();write(args.output/'record.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in ('oracle','anchors','before','after')},indent=2))
    return 1 if record['errors'] else 0


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--tool',type=Path,required=True);p.add_argument('--dll',type=Path,required=True);p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
