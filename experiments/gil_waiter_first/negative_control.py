"""Request arrives after the consumer context is captured, while other threads run."""
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
import uuid

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
    with p.open('x') as f:json.dump(v,f,indent=2)


if __name__=='__main__':
    plan=read(HERE/'plan01.json');output=HERE/'runs/negative01';output.mkdir(parents=True,exist_ok=False);(output/'active.lock').mkdir()
    sys.path.insert(0,plan['native_helpers']);from observe import Observer;from winapi import anchor
    k=C.WinDLL('kernel32',use_last_error=True)
    k.CreateEventW.argtypes=[C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR];k.CreateEventW.restype=W.HANDLE
    k.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];k.WaitForSingleObject.restype=W.DWORD
    k.SetEvent.argtypes=[W.HANDLE];k.CloseHandle.argtypes=[W.HANDLE]
    record=dict(errors=[],oracle=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    target=observer=counter=None;shared=backing=None;events=[]
    try:
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
        assert sha(Path(plan['observer_path']))==plan['observer_sha256'] and sha(Path(plan['negative_oracle_path']))==plan['negative_oracle_sha256']
        assert sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        with (output/'target.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(HERE/'negative_fixture.py'),str(output/'target'),plan['negative_oracle_path']],stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+8
        while not (output/'target/ready.json').exists():
            if target.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Negative target ready missing')
            time.sleep(.002)
        ready=record['ready']=read(output/'target/ready.json');assert ready['pid']==target.pid
        backing=(output/'target/oracle.bin').open('r+b');shared=mmap.mmap(backing.fileno(),128)
        def probe(label):
            b=anchor();values=list(struct.unpack_from('<16Q',shared));confirm=struct.unpack_from('<Q',shared)[0];e=anchor()
            p=dict(label=label,begin=b,end=e,values=values,confirm=confirm);record['oracle'].append(p);return p
        counter=Observer([dict(pid=target.pid,tid=tid,role='consumer',name=n) for n,tid in ready['tids'].items()]);record['before']=counter.snapshot()
        prefix='Local\\IronJump-waiter-first-'+str(target.pid)+'-'+uuid.uuid4().hex;record['test_gate_prefix']=prefix
        for suffix in ('.pre','.go'):
            h=k.CreateEventW(None,True,False,prefix+suffix);assert h;events.append(h)
        stream=output/'samples.jsonl';command=[plan['observer_path'],str(target.pid),str(ready['tids']['waiter']),'1','250',str(ready['oracle_address']),str(stream)];record['command']=command
        with (output/'observer.log').open('xb') as log:
            observer=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,_NT_SYMBOL_PATH=plan['symbol_search_path'],IRONJUMP_WAITER_TEST_GATE=prefix))
        deadline=time.monotonic()+12
        while True:
            data=stream.read_bytes() if stream.exists() else b''
            if b'\n' in data:
                record['init']=json.loads(data.split(b'\n')[0]);assert record['init']['error'] is None;break
            if observer.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Negative observer init missing')
            time.sleep(.002)
        (output/'target/go').touch(exist_ok=False);deadline=time.monotonic()+3
        while True:
            p=probe('await_holder');v=p['values']
            if v[0]==p['confirm'] and v[0]%2==0 and v[1:3]==[1,ready['tids']['owner']] and v[9]>2:break
            if time.monotonic()>deadline:raise TimeoutError('Negative owner phase missing')
            time.sleep(.002)
        record['external_begin']=anchor();probe('before_snapshot');Path(str(stream)+'.go').touch(exist_ok=False)
        assert k.WaitForSingleObject(events[0],8000)==0;record['pre_event_observed']=anchor()
        probe('before_request');struct.pack_into('<Q',shared,8*8,1);record['gate_written']=anchor()
        for _ in range(8):time.sleep(.004);probe('requester_frozen_others_running')
        record['global_go']=anchor();assert k.SetEvent(events[1])
        deadline=time.monotonic()+10
        while observer.poll() is None:
            probe('sampling')
            if time.monotonic()>deadline:raise TimeoutError('Observer pending; preserve target and lock')
            time.sleep(.002)
        record['observer_returncode']=observer.returncode;record['external_end']=anchor();probe('after_snapshot')
        record['after']=counter.snapshot();counter.close();counter=None
        assert observer.returncode==0 and not (output/'observer.log').read_bytes()
        struct.pack_into('<Q',shared,10*8,1);target.wait(timeout=15);record['complete']=read(output/'target/complete.json')
        assert target.returncode==0 and not (output/'target.log').read_bytes()
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        record['observer_still_running']=observer is not None and observer.poll() is None
        if not record['observer_still_running'] and target is not None and target.poll() is None:
            if shared is not None:struct.pack_into('<Q',shared,8*8,2);struct.pack_into('<Q',shared,10*8,1)
            try:target.wait(timeout=15)
            except subprocess.TimeoutExpired:record['errors'].append('Target exit unconfirmed')
        record['target_still_running']=target is not None and target.poll() is None;record['target_returncode']=target.returncode if target is not None else None
        if shared is not None:shared.close();backing.close()
        if counter is not None:counter.close()
        for h in events:k.CloseHandle(h)
        record['lock_retained']=(output/'active.lock').is_dir();record['plan_sha256']=sha(HERE/'plan01.json');write(output/'record.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in ('oracle','before','after')},indent=2));raise SystemExit(bool(record['errors']))
