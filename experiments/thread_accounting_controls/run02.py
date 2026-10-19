"""Known workers, exited retained worker, and an invisible between-endpoints worker."""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from inventory02 import Inventory,summarize,enumerate_timed

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def burn(seconds):
    until=time.perf_counter()+seconds;blocks=0
    while time.perf_counter()<until:
        assert sum(range(10000))==49995000;blocks+=1
    return blocks

def main():
    plan=json.loads((HERE/'plan02.json').read_text());assert all(sha(HERE/n)==h for n,h in plan['sources'].items())
    sys.path.insert(0,str(HERE.parent/'wall_cpu_controls'));from probe import Probe,delta
    assert sha(HERE.parent/'wall_cpu_controls/probe.py')==plan['probe_sha256']
    folder=HERE/'runs/control02';folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir();result=dict(cases={},errors=[])
    try:
        for name in plan['cases']:
            go=threading.Event();release=threading.Event();workers=[];signals=[];row=dict(workers=[]);inv=None
            try:
                def start_worker(hold):
                    ready=threading.Event();done=threading.Event();signals.append((ready,done));record={};row['workers'].append(record)
                    def work():
                        try:
                            record['tid']=threading.get_native_id();ready.set();assert go.wait(10)
                            record['begin_ns']=time.perf_counter_ns();record['blocks']=burn(plan['seconds']);record['end_ns']=time.perf_counter_ns()
                            done.set()
                            if hold:assert release.wait(10)
                        except BaseException as exc:record['error']=repr(exc);ready.set();done.set()
                    t=threading.Thread(target=work);workers.append(t);t.start();assert ready.wait(10)
                if name!='transient_worker':
                    for _ in range(2 if name=='stable_workers' else 1):start_worker(name=='stable_workers')
                p=Probe();begin=time.perf_counter_ns();cpu=time.thread_time_ns();inv=Inventory()
                row['inventory_construction']=dict(before_ns=begin,after_ns=time.perf_counter_ns(),thread_cpu_ns=time.thread_time_ns()-cpu)
                row['enumeration_before']=enumerate_timed(inv)
                row['process_before']=p.snapshot();row['before']=inv.snapshot()
                row['before']['enumerated_tids']=row['enumeration_before']['tids']
                if name=='transient_worker':start_worker(False)
                go.set()
                for ready,done in signals:assert done.wait(10)
                if name!='stable_workers':
                    for t in workers:t.join(10);assert not t.is_alive()
                row['after']=inv.snapshot();row['process_after']=p.snapshot()
                row['enumeration_after']=enumerate_timed(inv);row['after']['enumerated_tids']=row['enumeration_after']['tids']
                assert row['enumeration_before']['after_ns']<=row['process_before']['before_ns'] and row['process_after']['after_ns']<=row['enumeration_after']['before_ns']
                row['summary']=summarize(row['before'],row['after'],plan['per_read_ns'],plan['group_ns']);row['process_delta']=delta(row['process_before'],row['process_after'])
                s=row['summary'];d=row['process_delta'];row['cpu_residual_ms']=d['process']['cpu_ms']-s['sum_cpu_ms']
                assert all('error' not in x for x in row['workers'])
                if name=='stable_workers':
                    assert s['retained_threads_pass'] and set(x['tid'] for x in row['workers'])<=set(x['tid'] for x in s['threads'])
                    assert s['sum_cpu_ms']>=500 and abs(row['cpu_residual_ms'])<=100
                elif name=='exited_worker':assert 'retained_thread_exited' in s['reasons'] and not s['retained_threads_pass']
                else:
                    assert s['retained_threads_pass'] and not s['whole_process_lifetime_coverage_proven']
                    assert row['cpu_residual_ms']>=500 and row['workers'][0]['tid'] not in inv.handles
                row['expected_control_pass']=True
            except BaseException as exc:row['error']=repr(exc);raise
            finally:
                go.set();release.set()
                for t in workers:t.join(10)
                row['workers_alive']=any(t.is_alive() for t in workers)
                if inv:
                    try:inv.close();row['handles_closed']=not inv.handles
                    except BaseException as exc:row['cleanup_error']=repr(exc)
                result['cases'][name]=row
                if row['workers_alive'] or row.get('cleanup_error'):raise RuntimeError('Cleanup unconfirmed; retained window')
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(complete=result.get('complete',False),errors=result['errors'])));return int(bool(result['errors']))

if __name__=='__main__':raise SystemExit(main())
