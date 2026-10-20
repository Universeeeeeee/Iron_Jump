"""Fixed consumer + real model work. No GUI, SDK, live input, sampler or speed claim."""
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'fixed_work_accounting'))
from logical_clock import for_thread
from counters import snapshot,validate

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def child(name):
    plan=json.loads((HERE/'plan01.json').read_text());assert name in plan['cases'];folder=HERE/'runs'/name;folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir()
    variant=plan['case_variants'][name];assert variant in ('concurrent','serial')
    result=dict(variant=variant,errors=[],model={},actual_load_disturbance_pass=False);real=time.perf_counter_ns;worker=None;go=threading.Event();ready=threading.Event();cancel=threading.Event();payloads=[];work_done=threading.Event();close_release=threading.Event()
    try:
        root=Path(plan['replay_root']);sys.path.insert(0,str(root/'experiments/walk_compute_offline_diagnosis'));import replay
        import cv2
        result['opencv_threads']=cv2.getNumThreads();assert result['opencv_threads']==8
        import numpy as np
        from vision.live_walking import _PreviewAdapter
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and sha(Path(replay.__file__))==plan['replay_sha256']
        assert sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256'] and sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
        base=replay.read(root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];assert all(sha(root/n)==v for n,v in base.items())
        source=Path(plan['input_root']);media=Path(plan['media_root']);model=Path(plan['model_path'])
        assert all(sha(source/n)==v for n,v in plan['input_sha256'].items()) and all(sha(media/n)==v for n,v in plan['media_sha256'].items()) and sha(model)==plan['model_sha256']
        with (media/'camera.csv').open() as f:index={int(x['capture_frame_index']):x for x in csv.DictReader(f)}
        frames=[];frame_evidence=[]
        with (media/'camera.mjpg').open('rb') as f:
            for frame_id in plan['frame_ids']:
                row=index[frame_id];f.seek(int(row['offset']));data=f.read(int(row['length']));frame=cv2.imdecode(np.frombuffer(data,dtype=np.uint8),cv2.IMREAD_COLOR);assert frame is not None
                frames.append(frame);frame_evidence.append(dict(frame_id=frame_id,media_sample_s=float(row['sample_time']),pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest(),shape=list(frame.shape)))
        app=replay.QCoreApplication.instance() or replay.QCoreApplication([]);trial=replay.Trial(source);engine=replay.GaitEngine(config=trial.cfg);quality=trial.quality(engine);engine.quality=quality
        quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
        def model_work():
            adapter=_PreviewAdapter(model);m=result['model'];m.update(errors=[],calls=[],tid=threading.get_native_id(),closed=False)
            try:
                m['open_begin_ns']=real();adapter.open();m['open_end_ns']=real();m['ready_ns']=real();ready.set()
                if not go.wait(120):raise TimeoutError('Consumer start not received')
                if cancel.is_set():return
                m['begin_ns']=real();cpu=time.thread_time_ns()
                for i in range(plan['model_calls']):
                    slot=i%len(frames);stamp=1000+50*i;begin=real();pose=adapter.infer_bgr(frames[slot],stamp);end=real();payloads.append(pose)
                    m['calls'].append(dict(ordinal=i,frame_id=plan['frame_ids'][slot],logical_ms=stamp,begin_ns=begin,end_ns=end))
                m.update(end_ns=real(),thread_cpu_ns=time.thread_time_ns()-cpu)
            except BaseException as exc:m['errors'].append(repr(exc));ready.set()
            finally:
                m['work_done_ns']=real();work_done.set()
                if not close_release.wait(180):m['errors'].append('Close release deadline expired')
                m['close_begin_ns']=real()
                try:adapter.close();m['closed']=not adapter.is_open
                except BaseException as exc:m['errors'].append(repr(exc))
                m['close_end_ns']=real()
        worker=threading.Thread(target=model_work,name='FixedModelWork');worker.start();assert ready.wait(60) and not result['model']['errors']
        time.perf_counter_ns=for_thread(threading.get_ident(),lambda:trial.clock,real)
        def feed(i):
            frame=trial.frames[i];trial.clock=frame.received_monotonic_ns;quality.on_frame(frame)
            if i==trial.start-1:trial.arm(quality)
        prep_begin=real();prep_cpu=time.thread_time_ns()
        for i in range(plan['raw_first']):feed(i)
        result['preparation']=dict(begin_ns=prep_begin,end_ns=real(),thread_cpu_ns=time.thread_time_ns()-prep_cpu,frames=plan['raw_first'])
        result['process_before']=snapshot(real)
        begin=real();cpu=time.thread_time_ns();progress=[]
        if variant=='concurrent':go.set()
        for i in range(plan['raw_first'],plan['raw_after_last']):
            feed(i)
            count=i-plan['raw_first']+1
            if count in plan['progress_frames']:progress.append(dict(frames=count,raw_last=i,host_ns=real(),thread_cpu_ns=time.thread_time_ns()-cpu))
        result['consumer']=dict(begin_ns=begin,end_ns=real(),thread_cpu_ns=time.thread_time_ns()-cpu,tid=threading.get_native_id(),frames=plan['raw_after_last']-plan['raw_first'])
        result['consumer_progress']=progress
        if variant=='serial':go.set()
        assert work_done.wait(180) and not result['model']['errors']
        result['process_after']=snapshot(real);result['close_release_ns']=real();close_release.set()
        worker.join(180);assert not worker.is_alive() and result['model']['closed'] and not result['model']['errors']
        for i in range(plan['raw_after_last'],trial.end):feed(i)
        trial.terminal_poll(quality);quality.halt();engine.overground.halt();report=asdict(engine.build_report(trial.report['finish_reason']));time.perf_counter_ns=real
        report.pop('export_frames');report.pop('export_timestamps');replay.equal(report,trial.report,'report');trial.check_quality(quality);p=engine.overground.processor
        replay.equal(p.event_audit,trial.saved['audit'],'audit');replay.equal(p.timeline,trial.saved['timeline'],'timeline');replay.equal(engine.overground._frame_filter.mirror_guard.events,trial.saved['mirror_events'],'mirror')
        with np.load(source/'raw_archive.npz') as raw:
            assert tuple(engine.overground.frames)==tuple(x.tobytes() for x in raw['bits'])
            assert np.array_equal(np.array(engine.overground.timestamps)-(p.origin or 0),raw['device_timestamps']-(p.origin or 0))
        hashes=[hashlib.sha256(json.dumps(None if pose is None else asdict(pose),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest() for pose in payloads]
        assert len(hashes)==plan['model_calls'] and all(sha(root/n)==v for n,v in base.items())
        assert all(sha(source/n)==v for n,v in plan['input_sha256'].items()) and all(sha(media/n)==v for n,v in plan['media_sha256'].items())
        result.update(complete=True,full_original_chain_exact=True,report_sha256=replay.digest(report),model_result_sha256=hashes,frame_evidence=frame_evidence)
        result['process_accounting']=validate(result)
        assert result['process_accounting']['accounting_pass'],result['process_accounting']
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        time.perf_counter_ns=real;cancel.set();go.set();close_release.set()
        if worker is not None and worker.is_alive():worker.join(180)
        result['worker_alive']=worker is not None and worker.is_alive()
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    return int(bool(result['errors']) or result['worker_alive'])

if __name__=='__main__':raise SystemExit(child(sys.argv[1]))
