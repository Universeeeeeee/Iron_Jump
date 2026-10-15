"""Recorded outbound input through the production quality gate and session."""
import cProfile,json,pstats,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import numpy as np
from qtpy.QtCore import QCoreApplication,Qt
from config.walking_config import WalkingConfig
from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame
from hardware.walking_preflight import PreparedDevice
from hardware.beam_quality import BeamQualityPolicy
from engine.device_quality_session import DeviceQualitySession
from engine.overground_session import OvergroundSession
from engine.modes.walking_processor import WalkingProcessor
folder=Path(sys.argv[1]);out=Path(sys.argv[2]);meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8'));d=meta['device']
layout=DeviceLayout(tuple(SensorSegment(**s) for s in d['layout']['segments']),tuple(d['layout']['invalid_bit_indices']))
dev=PreparedDevice(layout,d['stream_id'],d['checked_sample_index'],0,3000,bad_indices=tuple(d['bad_indices']))
cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
app=QCoreApplication([]);session=OvergroundSession(cfg,WalkingProcessor);quality=DeviceQualitySession(cfg,BeamQualityPolicy(**d['policy']))
with np.load(folder/'raw_frames.npz') as archive:data={key:archive[key] for key in archive.files}
selected=np.flatnonzero((data['sample_indices']>d['checked_sample_index'])&(data['sample_indices']<=173400))
def frame(k):
 return SensorFrame(dev.stream_id,layout,int(data['frame_indices'][k]),int(data['sample_indices'][k]),int(data['received_ns'][k]),data['bits'][k].tobytes(),b'\x01'*768,data['wire'][k].tobytes())
quality._segments.observe(frame(selected[0]));quality.context=dev;session.start_prepared(dev)
quality.frame_ready.connect(lambda raw,processed,uncertain:session.on_frame(processed,raw,uncertain),Qt.DirectConnection)
def run():
 for k in selected:quality.on_frame(frame(k))
 session.halt()
started=time.perf_counter();pr=cProfile.Profile()
if '--no-profile' in sys.argv:run()
else:pr.runcall(run)
elapsed=time.perf_counter()-started
if '--no-profile' not in sys.argv:
 with out.with_suffix('.txt').open('w',encoding='utf-8') as stream:pstats.Stats(pr,stream=stream).sort_stats('cumtime').print_stats(30)
result={'frames':len(selected),'wall_s':elapsed,'device_s':len(selected)/1000,'summary':session.processor.summary()}
out.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(len(selected),elapsed,result['summary']['valid_touches'],result['summary']['valid_steps'],flush=True)
