"""Six fixed serial-work processes; change only time between process exits/launches."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from spacing import SystemReader,gap
from classify import state,spacing_quality
from verify import check,identity

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
emit=lambda row:print(json.dumps(row),flush=True)


def require():
    p=read(HERE/'plan01.json');proof=read(HERE/'preflight01.json')
    assert proof['passed'] and proof['plan_sha256']==sha(HERE/'plan01.json')
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in p['dependency_sources'].items())
    return p


if __name__=='__main__':
    p=require();folder=HERE/'runs';folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    status=dict(complete=False,controller_pid=os.getpid(),cases=[],errors=[])
    with (folder/'controller.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    reader=SystemReader();previous_exit=None
    try:
        reference=identity(read(HERE/'reference01.json'))
        for case in p['schedule']:
            name=case['id'];record=dict(case=case,errors=[],complete=False)
            if previous_exit is None:
                spacing=dict(previous_exit_observed_ns=None,requested_gap_seconds=None,system_samples=[])
            else:spacing=gap(previous_exit,case['gap_seconds'],reader,emit)
            child=None
            try:
                with (folder/(name+'.stdout')).open('xb') as out,(folder/(name+'.stderr')).open('xb') as err:
                    spacing['child_launch_before_ns']=time.perf_counter_ns()
                    child=subprocess.Popen([sys.executable,str(HERE/'workload.py'),name],stdout=out,stderr=err)
                    record['pid']=child.pid;record['returncode']=child.wait(timeout=480)
                    previous_exit=time.perf_counter_ns();record['exit_observed_ns']=previous_exit
                assert record['returncode']==0
                result=read(folder/name/'result.json');record['validation']=check(p,result)
                assert record['validation']['pass_all'] and identity(result)==reference
                assert result['variant']=='serial' and result['opencv_threads']==8
                record['state']=state(result,p['state_rules'])
                if spacing['previous_exit_observed_ns'] is not None:
                    record['spacing_quality']=spacing_quality(spacing,p['spacing_rules'])
                    assert record['spacing_quality']['spacing_pass']
                record['complete']=True
            except BaseException as exc:record['errors'].append(repr(exc))
            finally:
                record['child_still_running']=child is not None and child.poll() is None
                record['spacing']=spacing
                with (folder/(name+'.record.json')).open('x') as f:json.dump(record,f,indent=2)
                status['cases'].append(name)
                emit(dict(event='window_complete',case=name,pid=record.get('pid'),complete=record['complete'],
                    errors=record['errors'],state=record.get('state'),spacing_quality=record.get('spacing_quality')))
            if record['errors'] or record['child_still_running']:raise RuntimeError('Stop at failed/missing target: '+name)
        require();status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (folder/'status.json').open('x') as f:json.dump(status,f,indent=2)
    emit(status);raise SystemExit(bool(status['errors']))
