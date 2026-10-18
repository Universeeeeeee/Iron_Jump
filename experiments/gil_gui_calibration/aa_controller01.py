"""Four fixed fresh-process OFF/OFF pairs, feasibility only; no observer or humans."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
from atomic_io03 import write


def wait_file(path,child,seconds):
    deadline=time.monotonic()+seconds
    while not path.exists():
        if child.poll() is not None or time.monotonic()>deadline:raise TimeoutError('Missing '+str(path))
        time.sleep(.01)
    return read(path)


def case(name,stage,plan):
    folder=stage/name;folder.mkdir();target=None;counter=None;record=dict(errors=[])
    try:
        with (folder/'gui.log').open('xb') as log:
            target=subprocess.Popen([sys.executable,str(HERE/'entry02.py'),'--input',plan['input_root'],'--output',str(folder/'capture'),'--mode','walk','--variant','A','--probe','P','--load','fixed'],stdout=log,stderr=subprocess.STDOUT)
            record['target_pid']=target.pid
            marker=record['armed']=wait_file(folder/'capture/armed.json',target,50)
            assert marker['pid']==target.pid and set(marker['tids'])=={'gui','consumer','reader'} and len(set(marker['tids'].values()))==3
            prepare=subprocess.run(['powershell','-NoProfile','-File',str(HERE/'prepare_targets.ps1'),'-FormalStarted',str(folder/'capture/armed.json'),'-Output',str(folder/'targets.json')],capture_output=True,timeout=10)
            (folder/'target_preparation.log').write_bytes(prepare.stdout+prepare.stderr);assert prepare.returncode==0
            from observe import Observer
            from winapi import anchor
            targets=read(folder/'targets.json');counter=Observer(targets)
            start=marker['host_ns']+plan['offset_ns'];end=start+plan['duration_ns']
            while time.perf_counter_ns()<start:
                if target.poll() is not None:raise RuntimeError('Target exited before ROI')
                time.sleep(.005)
            record['anchors']=[anchor()];record['before']=counter.snapshot();record['before_done_ns']=time.perf_counter_ns()
            assert record['before_done_ns']-start<=plan['lateness_ns_max']
            while time.perf_counter_ns()<end:
                if target.poll() is not None:raise RuntimeError('Target exited inside ROI')
                time.sleep(.005)
            record['after_begin_ns']=time.perf_counter_ns();record['after']=counter.snapshot();record['anchors'].append(anchor())
            assert record['after_begin_ns']-end<=plan['lateness_ns_max']
            counter.close();counter=None
            target.wait(timeout=100);record['target_returncode']=target.returncode;assert target.returncode==0
        import semantics02
        m,*_=semantics02.verify(folder/'capture');assert m['sdk']['stop_success'] and not m['errors'] and not m['sdk_errors']
        for a,b in zip(record['before'],record['after']):
            assert a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns'])
            assert all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns'))
        assert len(record['before'])==len(record['after'])==len(targets)
        record.update(case_pass=True,full_semantics_exact=True,sdk=m['sdk'],camera=m['camera'],pose_draws=m['pose_draws'],video_indices=m['video_indices'])
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if counter is not None:counter.close()
        record['target_still_running']=target is not None and target.poll() is None
        write(folder/'record01.json',record)
    print(json.dumps(dict(case=name,passed=record.get('case_pass',False),errors=record['errors'])),flush=True)
    assert record.get('case_pass') and not record['errors'] and not record['target_still_running'],'Preserve invalid case and abort; never replace'


def main():
    plan=read(HERE/'aa_plan01.json');stage=HERE/'runs/off_aa01';stage.mkdir(parents=True,exist_ok=False);lock=stage/'active.lock';lock.mkdir();result=dict(errors=[],cases=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        frozen=read(HERE/'aa_frozen_sources01.json')['files']
        def unchanged():return all(sha(ROOT/n)==h for n,h in frozen.items()) and all(sha(ROOT/n)==h for n,h in plan['baseline_files'].items())
        assert unchanged();sys.path.insert(0,str(HERE))
        for name in plan['cases']:
            case(name,stage,plan);result['cases'].append(name);assert unchanged()
        result['all_fixed_cases_complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result['plan_sha256']=sha(HERE/'aa_plan01.json');result['lock_retained']=lock.is_dir();write(stage/'result01.json',result)
    print(json.dumps(result),flush=True);return int(bool(result['errors']))


if __name__=='__main__':raise SystemExit(main())
