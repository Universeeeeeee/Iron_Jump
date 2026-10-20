"""One frozen reference followed by one child delivery; no success-driven extension."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))

def require():
    p=read(HERE/'plan04.json');proof=read(HERE/'preflight04.json')
    assert proof['passed'] and proof['plan_sha256']==sha(HERE/'plan04.json')
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert sha(HERE/'selection01.json')==p['selection_sha256']
    return p

if __name__=='__main__':
    p=require();runs=HERE/'runs';runs.mkdir(exist_ok=False);(runs/'active.lock').mkdir()
    status=dict(complete=False,controller_pid=os.getpid(),steps=[],errors=[])
    try:
        commands=[('reference',[sys.executable,str(HERE/'reference.py'),str(runs/'reference01.json')]),
                  ('process',[sys.executable,str(HERE/'process_delivery.py'),str(runs/'process01')])]
        for name,command in commands:
            record=dict(name=name,command=command,complete=False,errors=[]);target=None
            try:
                with (runs/(name+'.stdout')).open('xb') as out,(runs/(name+'.stderr')).open('xb') as err:
                    target=subprocess.Popen(command,stdout=out,stderr=err);record['pid']=target.pid;record['returncode']=target.wait(timeout=300)
                assert record['returncode']==0 and b'Traceback' not in (runs/(name+'.stderr')).read_bytes()
                require();record['complete']=True
            except BaseException as exc:record['errors'].append(repr(exc))
            finally:
                record['target_still_running']=target is not None and target.poll() is None
                with (runs/(name+'.record.json')).open('x') as f:json.dump(record,f,indent=2)
                status['steps'].append(record)
            if record['errors'] or record['target_still_running']:raise RuntimeError('Stop at failed delivery step: '+name)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (runs/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status));raise SystemExit(bool(status['errors']))
