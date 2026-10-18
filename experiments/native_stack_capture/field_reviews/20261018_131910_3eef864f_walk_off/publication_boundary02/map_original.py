"""Unmeasured original-chain replay: map Processor publication samples to outer raw inputs."""
import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np


def main(args):
    args.output.mkdir(exist_ok=False)
    sys.path.insert(0,str(args.root/'experiments/walk_compute_offline_diagnosis'))
    import replay as original
    from engine.modes.walking_processor import WalkingProcessor
    app=original.QCoreApplication.instance() or original.QCoreApplication([])
    baseline=original.read(args.root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(original.file_sha(args.root/n)==v for n,v in baseline.items())
    trial=original.Trial(args.input)
    engine=original.GaitEngine(config=trial.cfg);quality=trial.quality(engine);engine.quality=quality
    quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
    process=WalkingProcessor.process;mapping=[];publications=[]
    outer=0;phase='input'
    def mapped(obj,frame,*a,**kw):
        before=len(obj.event_audit)
        result=process(obj,frame,*a,**kw)
        mapping.append([outer,frame.sample_index])
        for e in obj.event_audit[before:]:
            if e['action']=='publish':publications.append(dict(event=e,outer_raw_sample=outer,processor_sample=frame.sample_index,phase=phase))
        return result
    WalkingProcessor.process=mapped
    time.perf_counter_ns=lambda:trial.clock
    try:
        for i,frame in enumerate(trial.frames):
            outer=i;trial.clock=frame.received_monotonic_ns;quality.on_frame(frame)
            if i==trial.start-1:trial.arm(quality)
        phase='terminal';trial.terminal_poll(quality);quality.halt();engine.overground.halt()
        report=asdict(engine.build_report(trial.report['finish_reason']))
    finally:
        WalkingProcessor.process=process;time.perf_counter_ns=original.REAL_CLOCK
    report.pop('export_frames');report.pop('export_timestamps')
    original.equal(report,trial.report,'full unmodified report');trial.check_quality(quality)
    p=engine.overground.processor
    original.equal(p.event_audit,trial.saved['audit'],'event audit');original.equal(p.timeline,trial.saved['timeline'],'unmasked timeline')
    original.equal(engine.overground._frame_filter.mirror_guard.events,trial.saved['mirror_events'],'mirror history')
    with np.load(args.input/'raw_archive.npz') as archive:
        assert tuple(engine.overground.frames)==tuple(row.tobytes() for row in archive['bits'])
        assert np.array_equal(np.array(engine.overground.timestamps)-(p.origin or 0),archive['device_timestamps']-(p.origin or 0))
    assert trial.manifest=={n:original.file_sha(args.input/n) for n in trial.manifest}
    assert all(original.file_sha(args.root/n)==v for n,v in baseline.items())
    values=np.array(mapping,dtype=np.int64);assert len(values)==trial.meta['raw_buffer']['total_received_frames'] and np.all(np.diff(values[:,1])==1)
    np.save(args.output/'output_map.npy',values)
    with (args.output/'publications.json').open('x') as f:json.dump(publications,f,indent=2)
    checks=dict(full_report_exact=True,quality_runtime_exact=True,event_audit_exact=True,unmasked_timeline_exact=True,mirror_history_exact=True,raw_archive_exact=True,all_458_sources_unchanged=True,input_files_unchanged=True,output_map_count=len(values),max_filter_lag=int(max(values[:,0]-values[:,1])),report_canonical_sha256=original.digest(report),input_sha256=trial.manifest,script_sha256=original.file_sha(Path(__file__)),replay_helper_sha256=original.file_sha(args.root/'experiments/walk_compute_offline_diagnosis/replay.py'),scope='Semantic mapping only; no cost measurement, devices, GUI event loop, algorithm alternative or optimization AB.')
    with (args.output/'checks.json').open('x') as f:json.dump(checks,f,indent=2)
    print(json.dumps(dict(checks=checks,publications=publications),indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
