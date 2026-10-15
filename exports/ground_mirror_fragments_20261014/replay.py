"""Frozen before/after replay; raw evidence and production files are not rewritten."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from config.walking_config import WalkingConfig
from hardware.sensor_frame import DeviceLayout, SensorSegment, SensorFrame
from hardware.walking_preflight import PreparedDevice
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.beam_filter import GroundStabilityFilter
from engine.modes.walking_processor import WalkingProcessor
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.overground_running_processor import OvergroundRunningProcessor
OUT=Path(__file__).resolve().parent


def frozen(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


def run(folder, processor_class, filter_class, mode='walk'):
    meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
    d=meta['device']; geometry=d['layout']
    layout=DeviceLayout(tuple(SensorSegment(**s) for s in geometry['segments']),tuple(geometry['invalid_bit_indices']))
    device=PreparedDevice(layout,d['stream_id'],d['checked_sample_index'],0,3000,bad_indices=tuple(d['bad_indices']))
    config=WalkingConfig if mode=='walk' else OvergroundRunningConfig
    cfg=config(**{k:v for k,v in meta.items() if k in config.__dataclass_fields__
                         and config.__dataclass_fields__[k].init})
    p=processor_class(cfg,device); filt=filter_class(layout,device.bad_indices)
    path=folder/('matched_usb.npz' if (folder/'matched_usb.npz').exists() else 'raw_frames.npz')
    data=np.load(path); bits=data['bits']
    samples=data['sample_indices'] if 'sample_indices' in data else data['frame_indices'] if 'frame_indices' in data else np.arange(len(bits))+device.checked_sample_index+1
    counters=data['frame_indices'] if 'frame_indices' in data else samples
    wire=data['wire'] if 'wire' in data else np.packbits(1-bits,axis=1,bitorder='little')
    delivered=[]
    for n,index,row,payload in zip(samples,counters,bits,wire):
        raw=SensorFrame(device.stream_id,layout,int(index),int(n),int(n)*1000000,row.tobytes(),b'\x01'*layout.bit_count,payload.tobytes())
        for f in filt.feed(masked_frame(raw,device.bad_indices)):
            delivered.append(f.sample_index);p.process(f,masked_contact=uncertain_contact(f,device.bad_indices))
    for f in filt.flush():
        delivered.append(f.sample_index);p.process(f,masked_contact=uncertain_contact(f,device.bad_indices))
    assert delivered==samples.tolist()
    s=p.summary()
    return {'frames':len(bits),'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'counts':{k:s[k] for k in ('valid_touches','valid_steps','valid_cycles','confirmed_contacts','duration_s','valid_contact_durations','valid_step_lengths') if k in s},
            'mirror_events':getattr(getattr(filt,'mirror_guard',None),'events',[]),
            'touch_samples':[e['touch_sample'] for e in p.touch_events if e['active']],
            'source_restorations':[e for e in p.event_audit if e['action']=='source_uncertainty_resolved'],
            'visible_confirmed_samples':sum(sum(f['status']=='confirmed' for f in t['feet']) for t in p.timeline),
            'summary':s}


if __name__=='__main__':
    label=sys.argv[1]
    before_p=frozen('mirror_before_walking',OUT/'before/walking_processor.py').WalkingProcessor
    before_f=frozen('mirror_before_filter',OUT/'before/beam_filter.py').GroundStabilityFilter
    before_r=frozen('mirror_before_running',OUT/'before/overground_running_processor.py').OvergroundRunningProcessor
    result={}
    for name,path,mode in [('oct9_original','exports/ground_field_20261009/walk','walk'),
        ('oct9_v16','exports/walking_field_v16_20261009/walk','walk'),
        ('oct10','exports/ground_field_20261010_audit/walk','walk'),
        ('oct9_run','exports/ground_field_20261009/run','run'),
        ('oct9_v16_run','exports/walking_field_v16_20261009/run','run'),
        ('oct10_run','exports/ground_field_20261010_audit/run','run')]:
        folder=ROOT/path
        result[name]={}
        for version,processor,filt in [('before',before_p if mode=='walk' else before_r,before_f),
                                       ('after',WalkingProcessor if mode=='walk' else OvergroundRunningProcessor,GroundStabilityFilter)]:
            result[name][version]=run(folder,processor,filt,mode)
            r=result[name][version]
            print(name,version,r['counts'],'mirrors',len(r['mirror_events']),flush=True)
    (OUT/f'{label}_replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
