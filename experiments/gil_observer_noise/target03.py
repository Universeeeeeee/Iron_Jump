"""Fixed saved Walk through the unchanged synchronous chain; no devices or GUI loop."""
import argparse
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
    real=original.REAL_CLOCK;time.perf_counter_ns=lambda:trial.clock
    try:
        for i in range(start):feed(i)
        write(a.output/'ready.json',dict(pid=__import__('os').getpid(),tid=threading.get_native_id(),raw_first=start,raw_after_last=end))
        wait(a.output/'go');blocks=[];begin=real();cpu_begin=time.thread_time_ns()
        block_begin,block_cpu=begin,cpu_begin
        for i in range(start,end):
            feed(i)
            if (i-start+1)%1000==0 or i==end-1:
                now=real();cpu_now=time.thread_time_ns();blocks.append(dict(raw_first=start+len(blocks)*1000,raw_last=i,wall_begin_ns=block_begin,wall_end_ns=now,wall_ns=now-block_begin,thread_cpu_ns=cpu_now-block_cpu));block_begin,block_cpu=now,cpu_now
        cpu_end=time.thread_time_ns();finish=real()
        write(a.output/'roi.json',dict(raw_first=start,raw_after_last=end,frames=end-start,wall_begin_ns=begin,wall_end_ns=finish,wall_ns=finish-begin,thread_cpu_ns=cpu_end-cpu_begin,blocks=blocks))
        wait(a.output/'finish')
        for i in range(end,trial.end):feed(i)
        trial.terminal_poll(quality);quality.halt();engine.overground.halt();report=asdict(engine.build_report(trial.report['finish_reason']))
    finally:time.perf_counter_ns=real
    report.pop('export_frames');report.pop('export_timestamps')
    original.equal(report,trial.report,'full unmodified report');trial.check_quality(quality);p=engine.overground.processor
    original.equal(p.event_audit,trial.saved['audit'],'event audit');original.equal(p.timeline,trial.saved['timeline'],'unmasked timeline');original.equal(engine.overground._frame_filter.mirror_guard.events,trial.saved['mirror_events'],'mirror history')
    with np.load(a.input/'raw_archive.npz') as archive:
        assert tuple(engine.overground.frames)==tuple(row.tobytes() for row in archive['bits'])
        assert np.array_equal(np.array(engine.overground.timestamps)-(p.origin or 0),archive['device_timestamps']-(p.origin or 0))
    assert all(original.file_sha(a.input/n)==v for n,v in plan['input_sha256'].items()) and all(original.file_sha(a.root/n)==v for n,v in baseline.items())
    write(a.output/'complete.json',dict(full_report_exact=True,quality_runtime_exact=True,event_audit_exact=True,timeline_exact=True,mirror_exact=True,raw_archive_exact=True,inputs_unchanged=True,all_458_sources_unchanged=True,report_canonical_sha256=original.digest(report),numpy_version=np.__version__,finished_ns=real(),actual_load_disturbance_pass=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
