"""Independent synchronous NumPy oracle for the frozen clip, outside timing."""
import argparse,hashlib,json,sys,time
from dataclasses import asdict
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
from qtpy.QtCore import QCoreApplication
from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame
from hardware.beam_quality import BeamQualityPolicy
from engine.gait_engine import GaitEngine
from engine.device_quality_session import DeviceQualitySession
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig

def digest(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def canonical(report):
    for branch in (report['report_config_snapshot']['device'],report['report_config_snapshot']['beam_quality']['preflight']):branch.pop('checked_monotonic_ns')
    return report

def main(folder,mode,output):
    app=QCoreApplication([]);original=json.loads((folder/'report.json').read_text(encoding='utf-8'));meta=original['report_config_snapshot'];d=meta['device']
    layout=DeviceLayout(tuple(SensorSegment(**v) for v in d['layout']['segments']),tuple(d['layout']['invalid_bit_indices']))
    cls=WalkingConfig if mode=='walk' else OvergroundRunningConfig;cfg=cls(**{k:v for k,v in meta.items() if k in cls.__dataclass_fields__ and cls.__dataclass_fields__[k].init})
    engine=GaitEngine(config=cfg);quality=DeviceQualitySession(cfg,BeamQualityPolicy(**d['policy']),engine);engine.quality=quality
    quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
    evidence=json.loads((folder/'acquisition_evidence.json').read_text(encoding='utf-8'));assert not evidence['issues']
    with np.load(folder/'raw_frames.npz') as raw:
        first=int(np.searchsorted(raw['sample_indices'],d['checked_sample_index']-3500));checked=int(np.searchsorted(raw['sample_indices'],d['checked_sample_index']));end=checked+1+meta['raw_buffer']['total_received_frames']
        data={key:raw[key][first:end].copy() for key in raw.files}
    for k,n in enumerate(data['sample_indices']):
        m=evidence['frames'][first+k]
        frame=SensorFrame(m['stream_id'],layout,int(data['frame_indices'][k]),int(n),time.perf_counter_ns(),data['bits'][k].tobytes(),data['valid_bits'][k].tobytes(),data['wire'][k].tobytes(),int(data['dropped_frames_before'][k]),tuple(m['quality_flags']))
        quality.on_frame(frame)
        if n==d['checked_sample_index']:quality.arm_checked((quality._status()['device_key'],True));assert quality.context is not None
    quality.halt();engine.overground.halt();report=asdict(engine.build_report('manual'));report.pop('export_frames',None);report.pop('export_timestamps',None);canonical(report)
    runtime=quality._runtime;window=hashlib.sha256()
    for bits,changes in runtime._window:window.update(bits.tobytes());window.update(changes.tobytes())
    snapshot=quality.snapshot();snapshot['preflight'].pop('checked_monotonic_ns')
    state={'quality':snapshot,'runtime_counts':runtime._counts.tolist(),'runtime_transitions':runtime._transitions.tolist(),'runtime_healthy':runtime.healthy_samples,'runtime_window_sha256':window.hexdigest(),'audit':digest(engine.overground.processor.event_audit),'timeline':digest(list(engine.overground.processor.timeline)),'mirror_events':engine.overground._frame_filter.mirror_guard.events,'raw_archive_sha256':hashlib.sha256(b''.join(engine.overground.frames)).hexdigest()}
    component='walking_summary' if mode=='walk' else 'running_summary'
    assert report[component]==original[component],'Clip changed movement/event/metric semantics'
    output.mkdir(exist_ok=False,parents=True);(output/'report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8');(output/'state.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    print(mode,'oracle exact movement summary',len(data['sample_indices']),'source frames',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--mode',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.input,a.mode,a.output)
