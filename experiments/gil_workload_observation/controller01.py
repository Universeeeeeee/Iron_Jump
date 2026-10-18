"""One two-case OFF/OFF observability pair; original replay and no stack sampler."""
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];OLD=HERE.parent/'gil_gui_calibration'
sys.path.insert(0,str(OLD))
from aa_controller01 import read,sha,wait_file
from atomic_io03 import write
from observe import Observer
from winapi import anchor


def case(name,stage,plan):
    folder=stage/name;folder.mkdir();target=counter=None;record=dict(errors=[])
    try:
        with (folder/'gui.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(HERE/'entry01.py'),'--input',plan['input_root'],'--output',str(folder/'capture'),'--mode','walk','--variant','A','--probe','P','--load','fixed'],stdout=log,stderr=subprocess.STDOUT)
            record['target_pid']=target.pid;marker=record['armed']=wait_file(folder/'capture/armed.json',target,50);assert marker['pid']==target.pid
            p=subprocess.run(['powershell','-NoProfile','-File',str(HERE/'prepare_targets01.ps1'),'-FormalStarted',str(folder/'capture/armed.json'),'-Output',str(folder/'targets.json')],capture_output=True,timeout=10)
            (folder/'target_preparation.log').write_bytes(p.stdout+p.stderr);assert p.returncode==0
            counter=Observer(read(folder/'targets.json'));start=marker['host_ns']+plan['offset_ns'];end=start+plan['duration_ns']
            while time.perf_counter_ns()<start:
                if target.poll() is not None:raise RuntimeError('Target exited before ROI')
                time.sleep(.005)
            record['anchors']=[anchor()];record['before']=counter.snapshot();record['before_done_ns']=time.perf_counter_ns()
            assert record['before_done_ns']-start<=plan['lateness_ns_max']
            while time.perf_counter_ns()<end:
                if target.poll() is not None:raise RuntimeError('Target exited inside ROI')
                time.sleep(.005)
            record['after_begin_ns']=time.perf_counter_ns();record['after']=counter.snapshot();record['anchors'].append(anchor());counter.close();counter=None
            assert record['after_begin_ns']-end<=plan['lateness_ns_max']
            target.wait(timeout=100);record['target_returncode']=target.returncode;assert target.returncode==0
        import semantics02
        m,*_=semantics02.verify(folder/'capture')
        assert m['sdk']['stop_success'] and not m['sdk_errors']
        w=read(folder/'capture/workload01.json');assert w['pid']==target.pid and not w['running_services'] and not w['rows']['callback_errors']
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
        record.update(case_pass=True,full_semantics_exact=True)
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if counter is not None:counter.close()
        # There is no sampler that could own a process suspension in this pair.
        if target is not None and target.poll() is None:
            try:target.wait(timeout=100)
            except subprocess.TimeoutExpired:record['errors'].append('Target exit unconfirmed; preserve PID and lock')
        record['target_still_running']=target is not None and target.poll() is None
        record['plan_sha256']=sha(HERE/'plan02.json');write(folder/'record01.json',record)
    print(json.dumps(dict(case=name,passed=record.get('case_pass',False),errors=record['errors'])),flush=True)
    return record


if __name__=='__main__':
    plan=read(HERE/'plan02.json');stage=HERE/'runs/observation02';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir()
    status=dict(cases=[],errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        def unchanged():return all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['frozen_existing'].items())
        assert unchanged()
        for name in plan['cases']:
            r=case(name,stage,plan);status['cases'].append(name)
            assert r.get('case_pass') and not r['target_still_running'] and unchanged(),'Case invalid; retain and stop, never replace'
        status['all_cases_complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        status['lock_retained']=(stage/'active.lock').is_dir();status['plan_sha256']=sha(HERE/'plan02.json');write(stage/'result01.json',status)
    print(json.dumps(status),flush=True);raise SystemExit(bool(status['errors']))
