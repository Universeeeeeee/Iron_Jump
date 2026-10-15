"""Same outbound raw evidence; benchmark only the optical filter and processor."""
import cProfile,json,pstats,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import numpy as np
from config.walking_config import WalkingConfig
from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame
from hardware.walking_preflight import PreparedDevice
from hardware.beam_quality import masked_frame,uncertain_contact
from hardware.beam_filter import GroundStabilityFilter
from engine.modes.walking_processor import WalkingProcessor
folder=Path(sys.argv[1]);out=Path(sys.argv[2]);meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8'));d=meta['device']
layout=DeviceLayout(tuple(SensorSegment(**s) for s in d['layout']['segments']),tuple(d['layout']['invalid_bit_indices']))
dev=PreparedDevice(layout,d['stream_id'],d['checked_sample_index'],0,3000,bad_indices=tuple(d['bad_indices']))
cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
p=WalkingProcessor(cfg,dev);filt=GroundStabilityFilter(layout,dev.bad_indices)
archive=np.load(folder/'raw_frames.npz');data={key:archive[key] for key in archive.files};archive.close();selected=np.flatnonzero((data['sample_indices']>d['checked_sample_index'])&(data['sample_indices']<=173400))
def run():
 for k in selected:
  n=int(data['sample_indices'][k]);i=int(data['frame_indices'][k]);row=data['bits'][k];wire=data['wire'][k]
  f=SensorFrame(dev.stream_id,layout,i,n,int(data['received_ns'][k]),row.tobytes(),b'\x01'*768,wire.tobytes())
  for measured in filt.feed(masked_frame(f,dev.bad_indices)):p.process(measured,masked_contact=uncertain_contact(measured,dev.bad_indices))
 for measured in filt.flush():p.process(measured,masked_contact=uncertain_contact(measured,dev.bad_indices))
started=time.perf_counter();pr=cProfile.Profile();pr.runcall(run);elapsed=time.perf_counter()-started
pr.dump_stats(str(out.with_suffix('.prof')))
with out.with_suffix('.txt').open('w',encoding='utf-8') as stream:pstats.Stats(pr,stream=stream).sort_stats('cumtime').print_stats(30)
result={'frames':len(selected),'wall_s':elapsed,'device_s':len(selected)/1000,'summary':p.summary()}
out.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(len(selected),elapsed,p.summary()['valid_touches'],p.summary()['valid_steps'],flush=True)
