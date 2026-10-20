"""Exact saved-input filter/processor/session block profile; no GUI or device."""
from dataclasses import asdict
import hashlib,json,platform,sys,time
from pathlib import Path
import numpy as np
from qtpy.QtCore import QCoreApplication
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'))
from semantics02 import digest
from config.walking_config import WalkingConfig
from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame
from hardware.walking_preflight import PreparedDevice
from hardware.beam_quality import BeamQualityPolicy,masked_frame
from engine.gait_engine import GaitEngine
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'));sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();REAL=time.perf_counter_ns

def one(raw,saved_report,saved_state):
 m=saved_report['report_config_snapshot'];d=m['device'];layout=DeviceLayout(tuple(SensorSegment(**v) for v in d['layout']['segments']),tuple(d['layout']['invalid_bit_indices']))
 context=PreparedDevice(layout,d['stream_id'],d['checked_sample_index'],d['checked_monotonic_ns'],d['healthy_samples'],d['sample_rate_hz'],BeamQualityPolicy(**d['policy']),tuple(d['bad_indices']),tuple(d['bad_types']),d['stability'],d['segment_selection'])
 cfg=WalkingConfig(**{k:v for k,v in m.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init});frames=[]
 for i,n in enumerate(raw['sample_indices']):
  if n<=d['checked_sample_index']:continue
  frame=SensorFrame(d['stream_id'],layout,int(raw['frame_indices'][i]),int(n),int(raw['received_ns'][i]),raw['bits'][i].tobytes(),raw['valid_bits'][i].tobytes(),raw['wire'][i].tobytes(),int(raw['dropped_frames_before'][i]),())
  frames.append((frame,masked_frame(frame,context.bad_indices)))
 engine=GaitEngine(config=cfg);engine.begin_quality_session(context);rows=[];clock=[frames[0][0].received_monotonic_ns]
 time.perf_counter_ns=lambda:clock[0]
 try:
  for start in range(0,len(frames),1000):
   wall=REAL();cpu=time.thread_time_ns()
   for raw_frame,processed in frames[start:start+1000]:clock[0]=raw_frame.received_monotonic_ns;engine.process_quality_frame(raw_frame,processed,False)
   count=len(frames[start:start+1000]);rows.append(dict(first_sample=frames[start][0].sample_index,last_sample=frames[start+count-1][0].sample_index,samples=count,wall_ns=REAL()-wall,thread_cpu_ns=time.thread_time_ns()-cpu))
  engine.overground.halt()
 finally:time.perf_counter_ns=REAL
 processor=engine.overground.processor
 assert digest(processor.event_audit)==saved_state['audit'] and digest(list(processor.timeline))==saved_state['timeline']
 archive=hashlib.sha256(b''.join(engine.overground.frames)).hexdigest();assert archive==saved_state['raw_archive_sha256']
 return dict(blocks=rows,event_audit_sha256=saved_state['audit'],timeline_sha256=saved_state['timeline'],raw_archive_sha256=archive,exact_algorithm_state=True)
if __name__=='__main__':
 p=read(HERE/'plan01.json');folder=Path(p['input_folder']);assert all(sha(folder/n)==v for n,v in p['input_sha256'].items());assert all(sha(ROOT/n)==v for n,v in p['formal_sha256'].items())
 app=QCoreApplication.instance() or QCoreApplication([]);report=read(folder/'report.json');state=read(folder/'state.json')
 with np.load(folder/'raw_frames.npz') as z:raw={k:z[k].copy() for k in z.files}
 result=dict(platform=platform.platform(),python=sys.version,repeats=[one(raw,report,state) for _ in range(p['repeats'])],scope='Original filter/processor/session with saved processed-equivalent frames; DeviceQualitySession and GUI/IPC excluded.')
 (HERE/'result01.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
