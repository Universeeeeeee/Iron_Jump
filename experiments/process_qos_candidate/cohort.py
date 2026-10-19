"""Exactly four frozen pairs; fail closed and retain every attempted window."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from gate import require_gate
from verify import check,identity

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    require_gate(HERE);plan=read(HERE/'plan01.json');stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir()
    status=dict(complete=False,cases=[],errors=[]);reference=identity(read(HERE/'reference01.json'))
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=__import__('os').getpid()),f)
    try:
        for name in plan['cases']:
            require_gate(HERE)
            assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                child=subprocess.Popen([sys.executable,str(HERE/'workload.py'),name],stdout=out,stderr=err)
                row=dict(case=name,pid=child.pid);status['cases'].append(row)
                try:row['exit_code']=child.wait(timeout=480)
                except subprocess.TimeoutExpired:status['unconfirmed_target_pid']=child.pid;raise
            assert row['exit_code']==0
            r=read(stage/name/'result.json');q=read(stage/(name+'_qos.json'));native=read(stage/(name+'_native')/'result01.json')
            row['validation']=check(plan,r)
            assert row['validation']['pass_all'] and identity(r)==reference and r['opencv_threads']==8
            assert native['complete'] and native['memory_released'] and not native['errors']
            assert not q['errors'] and q['returncode']==0 and q['configuration']['variant']==plan['qos_variants'][name] and q['at_end']==q['configuration']['after']
            print(json.dumps(row),flush=True)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(dict(complete=status['complete'],errors=status['errors'])),flush=True);raise SystemExit(bool(status['errors']))
