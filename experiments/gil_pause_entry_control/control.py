"""One baseline and one explicit early-owner-pause counterexample. Never an app run."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import mmap
import os
from pathlib import Path
import struct
import subprocess
import sys
import time


HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
    with p.open('x') as f:json.dump(v,f,indent=2)


def case(name,plan):
    output=HERE/'runs'/name;output.mkdir(parents=True,exist_ok=False);(output/'active.lock').mkdir()
    record=dict(case=name,errors=[],oracle=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    target=observer=counter=None;owner_handle=None;owner_paused=False;shared=None
    sys.path.insert(0,plan['native_helpers']);from observe import Observer;from winapi import anchor
    k=C.WinDLL('kernel32',use_last_error=True)
    k.OpenThread.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenThread.restype=W.HANDLE
    k.GetProcessIdOfThread.argtypes=[W.HANDLE];k.GetProcessIdOfThread.restype=W.DWORD
    for n in ('SuspendThread','ResumeThread'):
        getattr(k,n).argtypes=[W.HANDLE];getattr(k,n).restype=W.DWORD
    k.CloseHandle.argtypes=[W.HANDLE]
    try:
        assert all(sha(HERE/n)==h for n,h in plan['sources'].items())
        assert sha(Path(plan['observer_path']))==plan['observer_sha256'] and sha(HERE/'PauseOracle.dll')==plan['oracle_dll_sha256']
        assert sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        with (output/'target.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(HERE/'fixture.py'),str(output/'target'),str(HERE/'PauseOracle.dll')],stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+8
        while not (output/'target/ready.json').exists():
            if target.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Target ready missing')
            time.sleep(.002)
        ready=record['ready']=read(output/'target/ready.json');assert ready['pid']==target.pid
        backing=(output/'target/oracle.bin').open('r+b');shared=mmap.mmap(backing.fileno(),128)
        def probe(label):
            b=anchor();values=list(struct.unpack_from('<16Q',shared));confirm=struct.unpack_from('<Q',shared)[0];e=anchor()
            row=dict(label=label,begin=b,end=e,values=values,confirm=confirm);record['oracle'].append(row);return row
        counter=Observer([dict(pid=target.pid,tid=tid,role='consumer',name=n) for n,tid in ready['tids'].items()])
        record['before']=counter.snapshot()
        owner_handle=k.OpenThread(0x0802,False,ready['tids']['owner'])
        assert owner_handle and k.GetProcessIdOfThread(owner_handle)==target.pid
        stream=output/'samples.jsonl'
        command=[plan['observer_path'],str(target.pid),str(ready['tids']['waiter']),'1','250',str(ready['oracle_address']),str(stream)]
        record['command']=command
        with (output/'observer.log').open('xb') as log:
            observer=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,_NT_SYMBOL_PATH=plan['symbol_search_path']))
        deadline=time.monotonic()+12
        while True:
            data=stream.read_bytes() if stream.exists() else b''
            if b'\n' in data:
                record['init']=json.loads(data.split(b'\n')[0]);assert record['init']['error'] is None;break
            if observer.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Observer init missing')
            time.sleep(.002)
        (output/'target/go').touch(exist_ok=False);deadline=time.monotonic()+3
        while True:
            p=probe('await_holder');v=p['values']
            if v[0]==p['confirm'] and v[0]%2==0 and v[1]==1 and v[2]==ready['tids']['owner'] and v[9]>2:break
            if time.monotonic()>deadline:raise TimeoutError('Stable native holder missing')
            time.sleep(.002)
        probe('before_intervention')
        if name=='early_owner_pause01':
            b=anchor();previous=k.SuspendThread(owner_handle);owner_paused=previous!=0xffffffff
            record['suspend']=dict(begin=b,end=anchor(),previous=previous);assert previous==0
            # Independent delivered effect: owner's heartbeat stops while another advances.
            for _ in range(5):probe('owner_pause_delivery');time.sleep(.004)
            probe('before_request');struct.pack_into('<Q',shared,8*8,1);record['request_gate_written']=anchor()
            deadline=time.monotonic()+2
            while probe('await_request')['values'][4]!=1:
                if time.monotonic()>deadline:raise TimeoutError('Native request missing')
                time.sleep(.001)
            time.sleep(.05)
        record['external_begin']=anchor();probe('before_snapshot');Path(str(stream)+'.go').touch(exist_ok=False)
        deadline=time.monotonic()+10
        while observer.poll() is None:
            probe('sampling')
            if time.monotonic()>deadline:raise TimeoutError('Observer live; preserve suspension and handles')
            time.sleep(.003)
        record['external_end']=anchor();record['observer_returncode']=observer.returncode;probe('after_snapshot')
        record['after']=counter.snapshot();counter.close();counter=None
        assert observer.returncode==0 and not (output/'observer.log').read_bytes()
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        # Do not resume our owner while a live observer may own a global lock.
        record['observer_still_running']=observer is not None and observer.poll() is None
        if not record['observer_still_running']:
            if owner_paused:
                b=anchor();previous=k.ResumeThread(owner_handle);record['resume']=dict(begin=b,end=anchor(),previous=previous)
                if previous!=1:record['errors'].append('Owner resume count not confirmed: '+str(previous))
                owner_paused=previous==0xffffffff or previous>1
            if shared is not None and not owner_paused:
                if name=='baseline01':struct.pack_into('<Q',shared,8*8,2)
                struct.pack_into('<Q',shared,10*8,1)
            if target is not None:
                try:target.wait(timeout=15)
                except subprocess.TimeoutExpired:record['errors'].append('Target exit unconfirmed')
        if target is not None:
            record['target_still_running']=target.poll() is None;record['target_returncode']=target.returncode
        record['owner_pause_outstanding']=owner_paused
        if (output/'target/complete.json').exists():record['complete']=read(output/'target/complete.json')
        if shared is not None:shared.close();backing.close()
        if owner_handle is not None:k.CloseHandle(owner_handle)
        if counter is not None:counter.close()
        record['lock_retained']=(output/'active.lock').is_dir();record['plan_sha256']=sha(HERE/'plan01.json')
        write(output/'record.json',record)
    return record


if __name__=='__main__':
    plan=read(HERE/'plan01.json')
    for name in plan['cases']:
        result=case(name,plan)
        print(json.dumps({k:v for k,v in result.items() if k not in ('oracle','before','after')},indent=2),flush=True)
        if result['errors'] or result.get('target_still_running') or result['observer_still_running']:raise SystemExit(1)
