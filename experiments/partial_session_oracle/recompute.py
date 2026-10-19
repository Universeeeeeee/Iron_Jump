"""Original frame/quality/filter/processor replay using retained inputs and observed cut."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
plain=lambda v:json.loads(json.dumps(v,ensure_ascii=False))

def recompute(input_root,actor_folder,checked,reason):
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/fixed_work_accounting'))
    import numpy as np
    from qtpy.QtCore import QCoreApplication
    from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame
    from hardware.beam_quality import BeamQualityPolicy
    from config.walking_config import WalkingConfig
    from engine.gait_engine import GaitEngine
    from engine.device_quality_session import DeviceQualitySession
    from logical_clock import for_thread
    sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'));from semantics02 import digest
    input_root=Path(input_root);actor_folder=Path(actor_folder)
    source=read(input_root/'report.json')['report_config_snapshot'];evidence=read(input_root/'acquisition_evidence.json');assert not evidence['issues']
    layout=DeviceLayout(tuple(SensorSegment(**v) for v in source['device']['layout']['segments']),tuple(source['device']['layout']['invalid_bit_indices']))
    cutoff=read(actor_folder/'result.json')['accepted_last_sample']
    assert source['device']['checked_sample_index']==checked<=cutoff
    with np.load(actor_folder/'raw_frames.npz') as z:actual={k:z[k].copy() for k in z.files}
    with np.load(input_root/'raw_frames.npz') as z:
        positions=np.searchsorted(z['sample_indices'],actual['sample_indices'])
        assert np.array_equal(z['sample_indices'][positions],actual['sample_indices'])
        for key in ('frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(z[key][positions],actual[key]),key
    cfg=WalkingConfig(**{k:v for k,v in source.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
    app=QCoreApplication.instance() or QCoreApplication([])
    engine=GaitEngine(config=cfg);engine.paused=True;quality=DeviceQualitySession(cfg,BeamQualityPolicy(),engine);engine.quality=quality
    quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
    real=time.perf_counter_ns;clock=[int(actual['received_ns'][0])];armed=False;formal=0;preflight=0
    time.perf_counter_ns=for_thread(threading.get_ident(),lambda:clock[0],real)
    try:
        for i,sample in enumerate(actual['sample_indices']):
            sample=int(sample)
            if sample>cutoff:break
            info=evidence['frames'][int(positions[i])];clock[0]=int(actual['received_ns'][i])
            frame=SensorFrame(info['stream_id'],layout,int(actual['frame_indices'][i]),sample,clock[0],actual['bits'][i].tobytes(),actual['valid_bits'][i].tobytes(),actual['wire'][i].tobytes(),int(actual['dropped_frames_before'][i]),tuple(info['quality_flags']))
            quality.latest_received_frame=frame;quality.on_frame(frame)
            if sample==checked:
                quality.arm_checked((quality._status()['device_key'],True));assert quality.context is not None
                armed=True
            if sample>checked:formal+=1
            else:preflight+=1
        assert armed and formal==cutoff-checked
        # Same ordered stop operations as original SessionController._do_stop.
        quality.halt();engine.overground.halt();engine._paused=True;engine._finished=True
        if getattr(engine,'_stop_timer',None):engine._stop_timer.stop()
        report=asdict(engine.build_report(reason));report.pop('export_frames',None);report.pop('export_timestamps',None)
        runtime=quality._runtime;window_hash=hashlib.sha256()
        for bits,changes in runtime._window:window_hash.update(bits.tobytes());window_hash.update(changes.tobytes())
        state=dict(quality=quality.snapshot(),runtime_counts=runtime._counts.tolist(),runtime_transitions=runtime._transitions.tolist(),runtime_healthy=runtime.healthy_samples,runtime_window_sha256=window_hash.hexdigest(),audit=digest(engine.overground.processor.event_audit),timeline=digest(list(engine.overground.processor.timeline)),mirror_events=engine.overground._frame_filter.mirror_guard.events,raw_archive_sha256=hashlib.sha256(b''.join(engine.overground.frames)).hexdigest())
        return plain(report),plain(state),dict(accepted_last_sample=cutoff,preflight_frames=preflight,formal_frames=formal,ingress_tail_not_reprocessed=int(np.count_nonzero(actual['sample_indices']>cutoff)),reason=reason)
    finally:
        time.perf_counter_ns=real
        quality._timer.stop();engine.overground._timer.stop()
