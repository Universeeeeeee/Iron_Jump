"""Instrumented fixed ROI call inventory, never a timing/overhead qualification."""
from observer import Observer
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def child(name):
    plan=json.loads((HERE/'plan01.json').read_text());assert name in plan['cases'];folder=HERE/'runs'/name;folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir();result=dict(errors=[],actual_load_disturbance_pass=False);real=time.perf_counter_ns;profiler=None
    try:
        root=Path(plan['replay_root']);sys.path.insert(0,str(root/'experiments/walk_compute_offline_diagnosis'));import replay
        import numpy as np
        assert sha(HERE/'run.py')==plan['run_sha256'] and sha(Path(replay.__file__))==plan['replay_sha256']
        base=replay.read(root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];assert all(sha(root/n)==v for n,v in base.items())
        source=Path(plan['input_root']);assert all(sha(source/n)==v for n,v in plan['input_sha256'].items())
        app=replay.QCoreApplication.instance() or replay.QCoreApplication([]);trial=replay.Trial(source);engine=replay.GaitEngine(config=trial.cfg);quality=trial.quality(engine);engine.quality=quality
        quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
        def feed(i):
            frame=trial.frames[i];trial.clock=frame.received_monotonic_ns;quality.on_frame(frame)
            if i==trial.start-1:trial.arm(quality)
        time.perf_counter_ns=lambda:trial.clock
        for i in range(plan['raw_first']):feed(i)
        profiler=Observer();profiler.enable()
        for i in range(plan['raw_first'],plan['raw_after_last']):feed(i)
        profiler.disable()
        for i in range(plan['raw_after_last'],trial.end):feed(i)
        trial.terminal_poll(quality);quality.halt();engine.overground.halt();report=asdict(engine.build_report(trial.report['finish_reason']));time.perf_counter_ns=real
        report.pop('export_frames');report.pop('export_timestamps');replay.equal(report,trial.report,'full report');trial.check_quality(quality);p=engine.overground.processor
        replay.equal(p.event_audit,trial.saved['audit'],'audit');replay.equal(p.timeline,trial.saved['timeline'],'timeline');replay.equal(engine.overground._frame_filter.mirror_guard.events,trial.saved['mirror_events'],'mirror')
        with np.load(source/'raw_archive.npz') as raw:
            assert tuple(engine.overground.frames)==tuple(x.tobytes() for x in raw['bits'])
            assert np.array_equal(np.array(engine.overground.timestamps)-(p.origin or 0),raw['device_timestamps']-(p.origin or 0))
        assert all(sha(root/n)==v for n,v in base.items()) and all(sha(source/n)==v for n,v in plan['input_sha256'].items())
        result.update(complete=True,full_original_semantics_exact=True,report_sha256=replay.digest(report),ownership=profiler.result(),ROI_frames=plan['raw_after_last']-plan['raw_first'],
                      scope='Selected pure helper inputs/outputs only. No memoization or skipped original calls, no timings or cost shares. Original full-chain outcomes checked.')
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        if profiler is not None:profiler.disable()
        time.perf_counter_ns=real
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
