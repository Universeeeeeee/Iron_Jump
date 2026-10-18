"""Fixed saved Walk through the unchanged synchronous chain; no devices or GUI loop."""
import argparse
import gc
from cpu_probe import CpuProbe
from array import array
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading
import time


from atomic_io03 import write
def wait(p):
    deadline=time.monotonic()+30
    while not p.exists():
        if time.monotonic()>deadline:raise TimeoutError('Missing '+str(p))
        time.sleep(.002)


def main(a):
    a.output.mkdir(exist_ok=False)
    sys.path.insert(0,str(a.root/'experiments/walk_compute_offline_diagnosis'));import replay as original
    import numpy as np
    plan=original.read(a.plan);baseline=original.read(a.root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(original.file_sha(a.root/n)==v for n,v in baseline.items())
    assert all(original.file_sha(a.input/n)==v for n,v in plan['input_sha256'].items())
    app=original.QCoreApplication.instance() or original.QCoreApplication([])
    trial=original.Trial(a.input);engine=original.GaitEngine(config=trial.cfg);quality=trial.quality(engine);engine.quality=quality
    quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
    start,end=plan['raw_first'],plan['raw_after_last'];assert trial.start<start<end<trial.end
    def feed(i):
        frame=trial.frames[i];trial.clock=frame.received_monotonic_ns;quality.on_frame(frame)
        if i==trial.start-1:trial.arm(quality)
    real=original.REAL_CLOCK
    cpu_probe=CpuProbe(plan['cpu_probe_dll'],real);cpu_topology=cpu_probe.topology();power_before=cpu_probe.power();cpu_points=[]
    gc_buffer=array('Q',[0])*(8192*6);gc_used=[0];gc_overflow=[False];gc_phase=[0]
    prior_callbacks=len(gc.callbacks)
    def gc_event(kind,info):
        n=gc_used[0]
        if n>=8192:gc_overflow[0]=True;return
        base=n*6;gc_buffer[base]=real();gc_buffer[base+1]=time.thread_time_ns();gc_buffer[base+2]=0 if kind=='start' else 1;gc_buffer[base+3]=info['generation'];gc_buffer[base+4]=gc_phase[0];gc_buffer[base+5]=threading.get_native_id();gc_used[0]=n+1
    gc.callbacks.append(gc_event)
    time.perf_counter_ns=lambda:trial.clock
    try:
        for i in range(start):feed(i)
        write(a.output/'ready.json',dict(pid=__import__('os').getpid(),tid=threading.get_native_id(),raw_first=start,raw_after_last=end))
        wait(a.output/'go');blocks=[];gc_before=gc.get_stats();cpu_points.append(dict(boundary='before_roi',**cpu_probe.current()));gc_phase[0]=1;begin=real();cpu_begin=time.thread_time_ns()
        block_begin,block_cpu=begin,cpu_begin
        for i in range(start,end):
            feed(i)
            if (i-start+1)%1000==0 or i==end-1:
                now=real();cpu_now=time.thread_time_ns();blocks.append(dict(raw_first=start+len(blocks)*1000,raw_last=i,wall_begin_ns=block_begin,wall_end_ns=now,wall_ns=now-block_begin,thread_cpu_ns=cpu_now-block_cpu));block_begin,block_cpu=now,cpu_now;cpu_points.append(dict(boundary='after_'+str(i),**cpu_probe.current()))
        cpu_end=time.thread_time_ns();finish=real();gc_phase[0]=2;gc_after=gc.get_stats()
        write(a.output/'roi.json',dict(raw_first=start,raw_after_last=end,frames=end-start,wall_begin_ns=begin,wall_end_ns=finish,wall_ns=finish-begin,thread_cpu_ns=cpu_end-cpu_begin,blocks=blocks))
        wait(a.output/'finish')
        for i in range(end,trial.end):feed(i)
        trial.terminal_poll(quality);quality.halt();engine.overground.halt();report=asdict(engine.build_report(trial.report['finish_reason']))
    finally:
        time.perf_counter_ns=real
        gc.callbacks.remove(gc_event)
    report.pop('export_frames');report.pop('export_timestamps')
    original.equal(report,trial.report,'full unmodified report');trial.check_quality(quality);p=engine.overground.processor
    original.equal(p.event_audit,trial.saved['audit'],'event audit');original.equal(p.timeline,trial.saved['timeline'],'unmasked timeline');original.equal(engine.overground._frame_filter.mirror_guard.events,trial.saved['mirror_events'],'mirror history')
    with np.load(a.input/'raw_archive.npz') as archive:
        assert tuple(engine.overground.frames)==tuple(row.tobytes() for row in archive['bits'])
        assert np.array_equal(np.array(engine.overground.timestamps)-(p.origin or 0),archive['device_timestamps']-(p.origin or 0))
    assert all(original.file_sha(a.input/n)==v for n,v in plan['input_sha256'].items()) and all(original.file_sha(a.root/n)==v for n,v in baseline.items())
    write(a.output/'cpu_delivery.json',dict(topology=cpu_topology,power_before=power_before,power_after=cpu_probe.power(),points=cpu_points,scope='Coarse endpoints only; no complete migration history or delivered-frequency measurement. Policy bits are getter metadata, not proof of physical delivery. Added diagnostic is not disturbance-qualified.'))
    write(a.output/'gc_events.json',dict(events=[list(gc_buffer[i*6:(i+1)*6]) for i in range(gc_used[0])],overflow=gc_overflow[0],prior_callbacks=prior_callbacks,before=gc_before,after=gc_after,scope='Rare GC start/stop callbacks with preallocated buffer. Diagnostic only; added callback is not itself disturbance-qualified and cannot retrospectively explain another run. No GC disabling/threshold/forced collection changes.'))
    write(a.output/'complete.json',dict(full_report_exact=True,quality_runtime_exact=True,event_audit_exact=True,timeline_exact=True,mirror_exact=True,raw_archive_exact=True,inputs_unchanged=True,all_458_sources_unchanged=True,report_canonical_sha256=original.digest(report),numpy_version=np.__version__,finished_ns=real(),actual_load_disturbance_pass=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
