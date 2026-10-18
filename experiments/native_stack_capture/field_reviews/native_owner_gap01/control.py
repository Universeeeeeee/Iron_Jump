"""One synthetic counterexample window; no application/device/ETW entry points."""
import argparse
import ctypes as C
import hashlib
import json
import mmap
from pathlib import Path
import struct
import subprocess
import sys
import time


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    with path.open('x') as out:json.dump(value,out,indent=2)


def main(args):
    plan=read(args.plan)
    args.output.mkdir(exist_ok=False)
    lock=args.output.parent/'active.lock';lock.mkdir()
    record=dict(errors=[],oracle=[],field_attribution_ready=False)
    target=observer=counter=None
    try:
        assert all(sha(args.plan.parent/p)==v for p,v in plan['sources'].items())
        assert sha(args.tool)==plan['observer_sha256'] and sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        assert sha(args.dll)==plan['oracle_dll_sha256']
        sys.path.insert(0,plan['native_helpers'])
        from winapi import anchor
        from observe import Observer
        with (args.output/'target.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(args.plan.parent/'fixture.py'),str(args.output/'target'),str(args.dll)],stdout=log,stderr=subprocess.STDOUT)
        record['target_pid']=target.pid
        deadline=time.monotonic()+8
        while not (args.output/'target/ready.json').exists():
            if target.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Target not ready')
            time.sleep(.01)
        ready=record['ready']=read(args.output/'target/ready.json');assert ready['pid']==target.pid
        # The role strings adapt the existing generic handle reader; names identify this synthetic fixture.
        targets=[dict(pid=target.pid,tid=tid,role=role,name=name) for name,tid,role in
                 [('native_owner',ready['tids']['native'],'consumer'),('heartbeat',ready['tids']['heartbeat'],'reader')]]
        counter=Observer(targets);record['before']=counter.snapshot();record['anchors']=[anchor()]
        with (args.output/'target/oracle.bin').open('rb') as backing:
            shared=mmap.mmap(backing.fileno(),32,access=mmap.ACCESS_READ)
            try:
                def sample_oracle():
                    b=time.perf_counter_ns();epoch,phase,tid,beat=struct.unpack_from('<QQQQ',shared);confirm=struct.unpack_from('<Q',shared)[0];e=time.perf_counter_ns()
                    row=[b,e,epoch,phase,tid,beat,confirm];record['oracle'].append(row);return row
                (args.output/'target/go').touch(exist_ok=False)
                deadline=time.monotonic()+5
                while True:
                    row=sample_oracle()
                    if row[2]==row[6] and row[2]%2==0 and row[3]==1:break
                    if target.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Native phase not observed')
                    time.sleep(.001)
                time.sleep(.3)
                with (args.output/'observer.log').open('xb') as log:
                    record['external_begin_ns']=time.perf_counter_ns()
                    observer=subprocess.Popen([str(args.tool),str(target.pid),str(plan['count']),str(plan['period_ms']),str(args.output/'samples.jsonl')],stdout=log,stderr=subprocess.STDOUT)
                    record['observer_pid']=observer.pid;deadline=time.monotonic()+8
                    while observer.poll() is None:
                        sample_oracle()
                        if time.monotonic()>deadline:raise TimeoutError('Observer still live; do not kill suspended target')
                        time.sleep(.001)
                    sample_oracle();record['external_end_ns']=time.perf_counter_ns()
                record['observer_returncode']=observer.returncode
                record['after']=counter.snapshot();record['anchors'].append(anchor())
                target.wait(timeout=10)
                sample_oracle()
            finally:shared.close()
        record['target_returncode']=target.returncode
        record['complete']=read(args.output/'target/complete.json')
        assert observer.returncode==target.returncode==0 and not (args.output/'observer.log').read_bytes()
        assert all(a['active'] and b['active'] and a['creation_100ns']==b['creation_100ns'] for a,b in zip(record['before'],record['after']))
        assert all(sha(args.plan.parent/p)==v for p,v in plan['sources'].items()) and sha(args.dll)==plan['oracle_dll_sha256'] and sha(args.tool)==plan['observer_sha256']
        record['capture_complete']=True
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if counter is not None:counter.close()
        record['target_still_running']=target is not None and target.poll() is None
        record['observer_still_running']=observer is not None and observer.poll() is None
        record['plan_sha256']=sha(args.plan)
        # No force kill: a timed-out observer could be within a suspend/resume read.
        write(args.output/'record.json',record)
        if not record['errors'] and not record['target_still_running'] and not record['observer_still_running']:lock.rmdir()
    print(json.dumps({k:v for k,v in record.items() if k not in ('oracle','before','after','anchors')},indent=2))
    return 1 if record['errors'] else 0


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--dll',type=Path,required=True);p.add_argument('--tool',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(p.parse_args()))
