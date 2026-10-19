"""Original pure helper, saved input multiplicities; no optimization comparison."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def restore(row):
    value=row['input']
    if value is None:return {}
    owner,ids,decisions=value
    return dict(recovery=dict(owner_id=owner,source_ids=list(ids)),source_decisions=[dict(source_id=s,outcome=o,owner_id=i) for s,o,i in decisions])

def child(name):
    plan=json.loads((HERE/'plan01.json').read_text());out=HERE/'runs'/name;out.mkdir(parents=True,exist_ok=False);(out/'active.lock').mkdir();result=dict(errors=[],actual_load_disturbance_pass=False)
    try:
        assert sha(HERE/'run.py')==plan['sources']['run.py'];root=Path(plan['replay_root']);sys.path.insert(0,str(root))
        from engine.ground_source_review import assigned_sources
        assert sha(root/'engine/ground_source_review.py')==plan['helper_sha256']
        rows=plan['groups'];prepared=[(restore(r),int(r['calls']),set(r['result'])) for r in rows]
        assert sum(n for _,n,_ in prepared)==plan['calls'] and all(n>0 for _,n,_ in prepared)
        for group,_,expected in prepared:assert assigned_sources(group)==expected
        order=plan['cases'][name];assert sorted(order)==list(range(len(prepared)));outputs=[]
        begin=time.perf_counter_ns();cpu=time.thread_time_ns()
        for index in order:
            group,count,expected=prepared[index]
            for _ in range(count):value=assigned_sources(group)
            outputs.append((index,value))
        cpu_end=time.thread_time_ns();end=time.perf_counter_ns()
        assert all(value==prepared[index][2] for index,value in outputs)
        assert sha(root/'engine/ground_source_review.py')==plan['helper_sha256']
        result.update(complete=True,calls=plan['calls'],order=order,wall_ns=end-begin,thread_cpu_ns=cpu_end-cpu,all_groups_original_results_exact=True,
                      scope='Grouped multiplicities, not original interleaved order. Original helper always executes. Loop/destruction bookkeeping included; construction/verification outside clocks. Not full-chain cache/GC/GIL environment.')
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        with (out/'result.json').open('x') as f:json.dump(result,f,indent=2)
    return int(bool(result['errors']))

if __name__=='__main__':
    if len(sys.argv)>1:raise SystemExit(child(sys.argv[1]))
    plan=json.loads((HERE/'plan01.json').read_text());stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(cases=[],errors=[])
    try:
        for name in plan['cases']:
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                p=subprocess.Popen([sys.executable,str(HERE/'run.py'),name],stdout=out,stderr=err)
                try:code=p.wait(timeout=30)
                except subprocess.TimeoutExpired:status['unconfirmed_pid']=p.pid;raise
            status['cases'].append(dict(name=name,exit_code=code));assert code==0
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status));raise SystemExit(bool(status['errors']))
