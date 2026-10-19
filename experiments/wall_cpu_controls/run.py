"""One fixed synthetic cohort, no devices, GUI, ETW or repeat-to-pass."""
import hashlib
import json
from pathlib import Path
import threading
import time
from probe import Probe,delta

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def burn(seconds):
    end=time.perf_counter()+seconds;blocks=0;checksum=0
    while time.perf_counter()<end:
        checksum=sum(range(10000));blocks+=1
    assert checksum==49995000 and blocks>0
    return dict(blocks=blocks,checksum=checksum)

def main():
    plan=json.loads((HERE/'plan01.json').read_text());assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    folder=HERE/'runs/control01';folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir()
    result=dict(cases={},errors=[],actual_load_disturbance_pass=False);probe=Probe()
    try:
        overhead=[probe.snapshot() for _ in range(100)]
        result['read_bracket_ns']=[x['after_ns']-x['before_ns'] for x in overhead]
        assert max(result['read_bracket_ns'])<=plan['read_bracket_ns_max']
        for name in plan['cases']:
            row={};worker=None;go=threading.Event();done=threading.Event();ready=threading.Event()
            try:
                if name=='worker_busy_main_wait':
                    def work():
                        try:
                            wp=Probe();ready.set();assert go.wait(10)
                            row['worker_before']=wp.snapshot();row['work']=burn(plan['seconds']);row['worker_after']=wp.snapshot()
                        except BaseException as exc:row['worker_error']=repr(exc)
                        finally:ready.set();done.set()
                    worker=threading.Thread(target=work);worker.start();assert ready.wait(10)
                row['before']=probe.snapshot()
                if name=='busy':row['work']=burn(plan['seconds'])
                elif name=='sleep':time.sleep(plan['seconds'])
                else:go.set();assert done.wait(10)
                row['after']=probe.snapshot()
                if worker:worker.join(10);assert not worker.is_alive() and 'worker_error' not in row
                d=delta(row['before'],row['after'],plan['read_bracket_ns_max']);row['delta']=d
                checks=dict(duration=d['wall_ms_bounds'][0]>=plan['seconds']*1000-50,
                    os_thread_clock_agrees=d['thread_time_ms_bounds'][0]-32<=d['thread']['cpu_ms']<=d['thread_time_ms_bounds'][1]+32,
                    process_covers_thread=d['process']['cpu_ms']+32>=d['thread']['cpu_ms'])
                if name=='busy':checks['executing']=d['thread']['cpu_ms']>=500 and d['thread']['cycles']>0
                else:checks['waiting_thread_low_CPU']=d['thread']['cpu_ms']<=250
                if name=='sleep':checks['idle_process_low_CPU']=d['process']['cpu_ms']<=250
                if worker:
                    wd=delta(row['worker_before'],row['worker_after'],plan['read_bracket_ns_max']);row['worker_delta']=wd
                    checks['worker_executing']=wd['thread']['cpu_ms']>=500 and wd['thread']['cycles']>0
                    checks['process_covers_worker']=d['process']['cpu_ms']+32>=wd['thread']['cpu_ms']
                    checks['different_threads']=row['before']['tid']!=row['worker_before']['tid'] and row['before']['pid']==row['worker_before']['pid']
                    checks['worker_bracket_inside_main']=row['before']['after_ns']<=row['worker_before']['before_ns']<=row['worker_after']['after_ns']<=row['after']['before_ns']
                row['checks']=checks;assert all(checks.values()),checks
            except BaseException as exc:row['error']=repr(exc);raise
            finally:
                go.set()
                if worker:worker.join(10)
                row['worker_alive']=bool(worker and worker.is_alive());result['cases'][name]=row
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result['sources_unchanged']=all(sha(HERE/n)==v for n,v in plan['sources'].items())
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(complete=result.get('complete',False),errors=result['errors'])));return int(bool(result['errors']))

if __name__=='__main__':raise SystemExit(main())
