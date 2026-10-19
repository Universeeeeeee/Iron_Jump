"""Fixed three-case original stage replay; original measure() gates retained."""
import gc
from array import array
import threading
import time
from measure import instrument
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def child(name):
    plan=json.loads((HERE/'plan01.json').read_text());order=plan['cases'][name];folder=HERE/'runs'/name;folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir();result=dict(errors=[],stages={},order=order,actual_load_disturbance_pass=False)
    try:
        root=Path(plan['replay_root']);sys.path.insert(0,str(root/'experiments/walk_compute_offline_diagnosis'));import replay
        assert sha(HERE/'run.py')==plan['run_sha256'] and sha(Path(replay.__file__))==plan['replay_sha256']
        base=replay.read(root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];assert all(sha(root/n)==v for n,v in base.items())
        assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
        app=replay.QCoreApplication.instance() or replay.QCoreApplication([]);trial=replay.Trial(Path(plan['input_root']));trial.oracle()
        result.update(report_sha256=trial.report_hash,formal_start=trial.start,formal_end=trial.end,final_state=trial.final_state)
        measure=instrument(replay);real=replay.REAL_CLOCK;buffer=array('Q',[0])*(8192*8);used=[0];overflow=[False];phase=[0]
        def event(kind,info):
            index=used[0]
            if index>=8192:overflow[0]=True;return
            offset=index*8;buffer[offset]=real();buffer[offset+1]=time.thread_time_ns();buffer[offset+2]=int(kind=='stop');buffer[offset+3]=info['generation'];buffer[offset+4]=phase[0];buffer[offset+5]=threading.get_native_id();buffer[offset+6]=info.get('collected',0);buffer[offset+7]=info.get('uncollectable',0);used[0]=index+1
        before_callbacks=len(gc.callbacks);gc.callbacks.append(event)
        try:
            for i,stage in enumerate(order,1):
                phase[0]=i;result['stages'][stage]=measure(trial,stage)
        finally:
            gc.callbacks.remove(event)
            result['gc']=dict(rows=[list(buffer[i*8:(i+1)*8]) for i in range(used[0])],overflow=overflow[0],prior_callbacks=before_callbacks,order=order)
        assert not overflow[0]
        assert all(sha(root/n)==v for n,v in base.items()) and all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
        result.update(complete=True,original_stage_semantics_exact=True)
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    return int(bool(result['errors']))

if __name__=='__main__':
    if len(sys.argv)>1:raise SystemExit(child(sys.argv[1]))
    plan=json.loads((HERE/'plan01.json').read_text());stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(cases=[],errors=[])
    try:
        for name in plan['cases']:
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                p=subprocess.Popen([sys.executable,str(HERE/'run.py'),name],stdout=out,stderr=err)
                try:code=p.wait(timeout=240)
                except subprocess.TimeoutExpired:status['unconfirmed_pid']=p.pid;raise
            status['cases'].append(dict(name=name,exit_code=code));assert code==0
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status));raise SystemExit(bool(status['errors']))
