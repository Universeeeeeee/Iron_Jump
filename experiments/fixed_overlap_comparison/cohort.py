"""Exactly four frozen pairs; no adaptive repetition or posthoc selection."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from verify import check,identity

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    plan=read(HERE/'plan01.json');plan_sha=sha(HERE/'plan01.json');stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(cases=[],errors=[],complete=False)
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=__import__('os').getpid()),f)
    reference=identity(read(HERE/'reference01.json'))
    try:
        for name in plan['cases']:
            assert sha(HERE/'plan01.json')==plan_sha and all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                child=subprocess.Popen([sys.executable,str(HERE/'workload.py'),name],stdout=out,stderr=err)
                try:code=child.wait(timeout=480)
                except subprocess.TimeoutExpired:status['unconfirmed_target_pid']=child.pid;raise
            row=dict(case=name,pid=child.pid,exit_code=code);status['cases'].append(row)
            assert code==0
            r=read(stage/name/'result.json');row['validation']=check(plan,r);row['matches_original_reference']=identity(r)==reference
            assert row['validation']['pass_all'] and row['matches_original_reference'] and r['variant']==plan['case_variants'][name]
            print(json.dumps(row),flush=True)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(dict(complete=status['complete'],errors=status['errors'])),flush=True);raise SystemExit(bool(status['errors']))
