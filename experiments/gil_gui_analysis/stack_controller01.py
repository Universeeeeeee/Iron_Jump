"""One separately frozen qualitative fixed-input native stack window; no retries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];OLD=ROOT/'experiments/gil_gui_calibration'
sys.path.insert(0,str(OLD))
from aa_controller01 import read,sha,wait_file
from atomic_io03 import write
from observe import Observer
from winapi import anchor


def wait_until(stamp,target):
    while time.perf_counter_ns()<stamp:
        if target.poll() is not None:raise RuntimeError('Target exited before fixed window')
        time.sleep(.005)


def main():
    plan=read(HERE/'stack_plan01.json');stage=HERE/'runs/stack01';stage.mkdir(parents=True,exist_ok=False);lock=stage/'active.lock';lock.mkdir()
    record=dict(errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False);target=observer=counter=None
    try:
        def unchanged():return all(sha(ROOT/n)==h for n,h in plan['frozen_sources'].items()) and sha(Path(plan['observer_path']))==plan['observer_sha256']
        assert unchanged() and all(sha(ROOT/n)==h for n,h in plan['baseline_files'].items())
        assert sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        with (stage/'gui.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(OLD/'entry02.py'),'--input',plan['input_root'],'--output',str(stage/'capture'),'--mode','walk','--variant','A','--probe','P','--load','fixed'],stdout=log,stderr=subprocess.STDOUT)
            record['target_pid']=target.pid;marker=record['armed']=wait_file(stage/'capture/armed.json',target,50);assert marker['pid']==target.pid
            prepared=subprocess.run(['powershell','-NoProfile','-File',str(HERE/'prepare_all_targets01.ps1'),'-FormalStarted',str(stage/'capture/armed.json'),'-Output',str(stage/'targets.json')],capture_output=True,timeout=10)
            (stage/'target_preparation.log').write_bytes(prepared.stdout+prepared.stderr);assert prepared.returncode==0
            counter=Observer(read(stage/'targets.json'))
            wait_until(marker['host_ns']+plan['initialize_offset_ns'],target)
            output=stage/'samples.jsonl';command=[plan['observer_path'],str(target.pid),str(marker['tids']['consumer']),str(plan['count']),str(plan['period_ms']),'0',str(output)]
            record['command']=command
            with (stage/'observer.log').open('xb') as observer_log:
                record['observer_launch_host_ns']=time.perf_counter_ns();observer=subprocess.Popen(command,stdout=observer_log,stderr=subprocess.STDOUT,env=dict(os.environ,_NT_SYMBOL_PATH=plan['symbol_search_path']));record['observer_pid']=observer.pid
                deadline=time.monotonic()+8
                while True:
                    data=output.read_bytes() if output.exists() else b''
                    if b'\n' in data:
                        record['init']=json.loads(data.split(b'\n')[0]);assert record['init']['kind']=='init' and record['init']['error'] is None;break
                    if observer.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Observer init; preserve all logs and lock')
                    time.sleep(.002)
                start=marker['host_ns']+plan['capture_offset_ns'];end=start+plan['duration_ns'];wait_until(start,target)
                record['anchors']=[anchor()];record['before']=counter.snapshot();record['capture_go_host_ns']=time.perf_counter_ns();assert record['capture_go_host_ns']-start<=plan['lateness_ns_max']
                Path(str(output)+'.go').touch(exist_ok=False)
                observer.wait(timeout=20);record['observer_returncode']=observer.returncode;record['observer_exit_host_ns']=time.perf_counter_ns()
                wait_until(end,target);record['after_begin_host_ns']=time.perf_counter_ns();record['after']=counter.snapshot();record['anchors'].append(anchor());counter.close();counter=None
                record['counter_end_late_ns']=record['after_begin_host_ns']-end
            target.wait(timeout=100);record['target_returncode']=target.returncode
        assert observer.returncode==0 and target.returncode==0 and not (stage/'observer.log').read_bytes()
        import semantics02
        m,*_=semantics02.verify(stage/'capture');assert m['sdk']['stop_success'] and not m['sdk_errors']
        assert unchanged()
        record.update(full_semantics_exact=True,sdk=m['sdk'],camera=m['camera'],pose_draws=m['pose_draws'],capture_and_target_complete=True)
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        # Never terminate an observer that might own a suspension scope.
        if target is not None and target.poll() is None and (observer is None or observer.poll() is not None):
            try:target.wait(timeout=100)
            except subprocess.TimeoutExpired:record['errors'].append('Target exit unconfirmed; preserve PID/lock')
        if counter is not None:counter.close()
        record['target_still_running']=target is not None and target.poll() is None;record['observer_still_running']=observer is not None and observer.poll() is None
        record['lock_retained']=lock.is_dir();record['plan_sha256']=sha(HERE/'stack_plan01.json');write(stage/'record01.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in ('before','after','anchors')},indent=2),flush=True);return int(bool(record['errors']))


if __name__=='__main__':raise SystemExit(main())
