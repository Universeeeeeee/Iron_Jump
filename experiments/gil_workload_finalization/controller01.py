"""One new protocol qualification case; no actual stack sampler or human inputs."""
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


if __name__=='__main__':
    plan=read(HERE/'plan01.json');stage=HERE/'runs/protocol01';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir()
    record=dict(errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False);target=counter=None
    try:
        def unchanged():return all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
        assert unchanged()
        assert sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
        assert all(sha(Path(n))==v for n,v in plan['external_native_sha256'].items())
        with (stage/'gui.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(HERE/'entry01.py'),'--input',plan['input_root'],'--output',str(stage/'capture'),'--mode','walk','--variant','A','--probe','P','--load','fixed'],stdout=log,stderr=subprocess.STDOUT)
            record['target_pid']=target.pid;marker=record['armed']=wait_file(stage/'capture/armed.json',target,50);assert marker['pid']==target.pid
            p=subprocess.run(['powershell','-NoProfile','-File',str(HERE/'prepare_targets01.ps1'),'-FormalStarted',str(stage/'capture/armed.json'),'-Output',str(stage/'targets.json')],capture_output=True,timeout=10)
            (stage/'target_preparation.log').write_bytes(p.stdout+p.stderr);assert p.returncode==0
            counter=Observer(read(stage/'targets.json'));start=marker['host_ns']+plan['offset_ns'];end=start+plan['duration_ns']
            while time.perf_counter_ns()<start:
                if target.poll() is not None:raise RuntimeError('Target exited before ROI')
                time.sleep(.005)
            record['anchors']=[anchor()];record['before']=counter.snapshot();record['before_done_ns']=time.perf_counter_ns();assert record['before_done_ns']-start<=plan['lateness_ns_max']
            while time.perf_counter_ns()<end:
                if target.poll() is not None:raise RuntimeError('Target exited inside ROI')
                time.sleep(.005)
            record['after_begin_ns']=time.perf_counter_ns();record['after']=counter.snapshot();record['anchors'].append(anchor());assert record['after_begin_ns']-end<=plan['lateness_ns_max']
            # The longer diagnostic lifetime is an explicit post-ROI observer
            # phase. Original replay watchdog/stop timeout and ROI gates unchanged.
            target.wait(timeout=220);record['target_returncode']=target.returncode
            record['terminal']=counter.snapshot();counter.close();counter=None
            assert target.returncode==0 and all(not x['active'] for x in record['terminal'])
        import semantics02
        m,*_=semantics02.verify(stage/'capture');assert m['sdk']['stop_success'] and not m['sdk_errors']
        f=read(stage/'capture/finalization.json');assert f['metadata_finalization_pass']
        initial=read(stage/'capture/application_return.json');record['application_return_model_confirmed']=all(initial['snapshot']['model_end_checks'].values())
        assert unchanged();record.update(protocol_case_pass=True,full_semantics_exact=True)
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if counter is not None:counter.close()
        if target is not None and target.poll() is None:
            try:target.wait(timeout=220)
            except subprocess.TimeoutExpired:record['errors'].append('Target exit unconfirmed; preserve PID/lock')
        record['target_still_running']=target is not None and target.poll() is None
        record['lock_retained']=(stage/'active.lock').is_dir();record['plan_sha256']=sha(HERE/'plan01.json');write(stage/'record01.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in ('before','after','terminal','anchors')},indent=2));raise SystemExit(bool(record['errors']))
