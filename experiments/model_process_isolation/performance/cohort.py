import hashlib
import json
from pathlib import Path
import subprocess
import sys
from gate import require_gate
from verify import check,identity
from delivery import verify_child

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    require_gate(HERE);plan=read(HERE/'plan01.json');stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir()
    reference=identity(read(HERE/'reference01.json'));status=dict(complete=False,cases=[],errors=[])
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=__import__('os').getpid()),f)
    try:
        for name in plan['cases']:
            require_gate(HERE);assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                child=subprocess.Popen([sys.executable,str(HERE/'workload.py'),name],stdout=out,stderr=err)
                row=dict(case=name,pid=child.pid);status['cases'].append(row)
                try:row['exit_code']=child.wait(timeout=600)
                except subprocess.TimeoutExpired:status['unconfirmed_target_pid']=child.pid;raise
            assert row['exit_code']==0
            result=read(stage/name/'result.json');row['validation']=check(plan,result)
            assert row['validation']['pass_all'] and identity(result)==reference
            if plan['isolation_variants'][name]=='process':
                row['model_delivery']=verify_child(result,read(stage/name/'vision_child/result.json'),[v['pixels_sha256'] for v in result['frame_evidence']],child.pid)
            row['complete_original_identity_matches']=True
            print(json.dumps(row),flush=True)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status),flush=True);raise SystemExit(bool(status['errors']))
