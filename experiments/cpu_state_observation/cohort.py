"""Four unchanged fixed-work windows with common read-only system observations."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from verify import check,identity

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def require_gate():
    plan=read(HERE/'plan01.json');gate=read(HERE/'preflight_passed01.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    return plan

if __name__=='__main__':
    plan=require_gate();folder=HERE/'runs';folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    status=dict(complete=False,cases=[],errors=[])
    with (folder/'controller.json').open('x') as f:json.dump(dict(pid=__import__('os').getpid()),f)
    try:
        reference=identity(read(HERE/'reference01.json'))
        for name in plan['cases']:
            require_gate();stop=folder/(name+'.stop')
            with (folder/(name+'.stdout')).open('xb') as out,(folder/(name+'.stderr')).open('xb') as err,(folder/(name+'.monitor.stderr')).open('xb') as merr:
                monitor=subprocess.Popen([sys.executable,str(HERE/'monitor.py'),str(folder/(name+'.system.jsonl')),str(stop),'540'],stderr=merr)
                child=subprocess.Popen([sys.executable,str(HERE/'workload.py'),name],stdout=out,stderr=err)
                row=dict(case=name,pid=child.pid,monitor_pid=monitor.pid);status['cases'].append(row)
                try:row['exit_code']=child.wait(timeout=480)
                except subprocess.TimeoutExpired:
                    status['unconfirmed_target_pid']=child.pid;status['unconfirmed_monitor_pid']=monitor.pid;raise
                stop.touch(exist_ok=False);row['monitor_exit']=monitor.wait(timeout=20)
            assert row['exit_code']==row['monitor_exit']==0
            r=read(folder/name/'result.json');row['validation']=check(plan,r)
            assert row['validation']['pass_all'] and identity(r)==reference
            p=r['preparation'];assert p['frames']==42237 and r['model']['ready_ns']<=p['begin_ns']<=p['end_ns']<=r['consumer']['begin_ns'] and p['thread_cpu_ns']>0
            print(json.dumps(row),flush=True)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (folder/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status),flush=True);raise SystemExit(bool(status['errors']))
