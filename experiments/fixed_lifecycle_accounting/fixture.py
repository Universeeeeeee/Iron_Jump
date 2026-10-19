"""One diagnostic fixed original workload with retained-thread accounting."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import os
from entry_query import query_new
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text());assert all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    child_plan=json.loads((HERE/'child/plan01.json').read_text());assert child_plan['cases']==plan['cases'] and child_plan['sources']=={}
    for key in ('input_sha256','media_sha256','model_sha256','raw_first','raw_after_last','frame_ids','model_calls'):assert child_plan[key]==plan[key]
    old=ROOT/'experiments/fixed_work_accounting';sys.path.insert(0,str(old));sys.path.insert(0,str(ROOT/'experiments/thread_accounting_controls'))
    import inventory02
    # The original replay uses a consumer-only logical sensor clock. Inventory
    # timestamps must retain the real clock even on that consumer thread.
    real=time.perf_counter_ns;inventory02.time=SimpleNamespace(perf_counter_ns=real,thread_time_ns=time.thread_time_ns)
    spec=importlib.util.spec_from_file_location('original_fixed_work',old/'run.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner);runner.HERE=HERE/'child'
    original=runner.snapshot;inv=None;record=dict(pid=os.getpid(),reads=[],errors=[],whole_process_lifetime_coverage_proven=False,actual_load_disturbance_pass=False)
    def snapshot(clock):
        global inv
        if not record['reads']:
            begin=real();cpu=time.thread_time_ns();inv=inventory02.Inventory()
            record['construction']=dict(before_ns=begin,after_ns=real(),thread_cpu_ns=time.thread_time_ns()-cpu)
            record['enumeration_before']=inventory02.enumerate_timed(inv)
            process=original(clock);threads=inv.snapshot();threads['enumerated_tids']=record['enumeration_before']['tids']
        else:
            assert len(record['reads'])==1
            threads=inv.snapshot();process=original(clock)
            record['enumeration_after']=inventory02.enumerate_timed(inv);threads['enumerated_tids']=record['enumeration_after']['tids']
            new=sorted(set(record['enumeration_after']['tids'])-set(record['enumeration_before']['tids']))
            record['new_thread_queries']=query_new(new,real)
        record['reads'].append(dict(process=process,threads=threads));return process
    runner.snapshot=snapshot;code=1
    try:
        code=runner.child('diagnostic01');record['workload_returncode']=code
        assert len(record['reads'])==2
        record['retained_accounting']=inventory02.summarize(*(r['threads'] for r in record['reads']),per_read_ns=plan['per_read_ns'],group_ns=plan['group_ns'])
        # Quality failures remain evidence, not reason to repeat this workload.
        record['source_unchanged']=all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items()) and all(sha(HERE/n)==v for n,v in plan['sources'].items())
    except BaseException as exc:record['errors'].append(repr(exc));code=1
    finally:
        if inv:
            try:inv.close();record['handles_closed']=not inv.handles
            except BaseException as exc:record['errors'].append(repr(exc));code=1
        with (HERE/'accounting01.json').open('x') as f:json.dump(record,f,indent=2)
    print(json.dumps(dict(workload_returncode=code,errors=record['errors'],retained_threads_pass=record.get('retained_accounting',{}).get('retained_threads_pass'))));raise SystemExit(code)
