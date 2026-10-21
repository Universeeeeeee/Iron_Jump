"""Offline regression of retained real frames through the original full chain."""
import argparse
from dataclasses import asdict
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from qtpy.QtCore import QCoreApplication
from config.test_config import config_from_dict
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame
from engine.gait_engine import GaitEngine
from engine.device_quality_session import DeviceQualitySession


def main(folder,output):
    original=json.loads((folder/'client/actor/report.json').read_text(encoding='utf-8'))
    acquisition=json.loads((folder/'client/actor/acquisition.json').read_text(encoding='utf-8'))
    assert not acquisition['issues']
    meta=original['report_config_snapshot'];config=config_from_dict(meta)
    app=QCoreApplication([]);engine=GaitEngine(config=config)
    quality=DeviceQualitySession(config,BeamQualityPolicy(**meta['beam_quality']['preflight']['policy']),engine)
    engine.quality=quality;quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
    checked=meta['device']['checked_sample_index'];layouts={key:DeviceLayout(tuple(SensorSegment(**segment) for segment in value['segments']),tuple(value['invalid_bit_indices'])) for key,value in acquisition['layouts'].items()}
    with np.load(folder/'client/actor/raw_frames.npz') as archive:
        source={name:archive[name].copy() for name in archive.files}
    if source:
        for i,n in enumerate(source['sample_indices']):
            descriptor=acquisition['frames'][i];stream=descriptor['stream_id'];frame=SensorFrame(stream,layouts[stream],int(source['frame_indices'][i]),int(n),time.perf_counter_ns(),source['bits'][i].tobytes(),source['valid_bits'][i].tobytes(),source['wire'][i].tobytes(),int(source['dropped_frames_before'][i]),tuple(descriptor['quality_flags']))
            quality.on_frame(frame)
            if int(n)==checked:
                assert quality.preflight.context.checked_sample_index==checked
                status=quality._status();assert status['ready'];quality.arm_checked((status['device_key'],True));assert quality.context is not None
    quality.halt();engine.overground.halt();actual=engine.build_report(original['finish_reason']);result=asdict(actual);result.pop('export_frames');result.pop('export_timestamps');result=json.loads(json.dumps(result))
    for name in ('device','beam_quality'):
        target=result['report_config_snapshot'][name]
        expected=meta[name]
        if name=='beam_quality':target=target['preflight'];expected=expected['preflight']
        target['checked_monotonic_ns']=expected['checked_monotonic_ns']
    s=result['walking_summary'];old=original['walking_summary'];assert s['recognized_steps']==len(s['footfalls'])==12
    assert len(s['steps'])==s['valid_steps']==s['valid_step_times']==7
    assert len(s['cycles'])==s['valid_cycles']==4
    unchanged={k:v for k,v in s.items() if k not in ('recognized_steps','footfalls','footfall_schema_version')};assert unchanged==old,'Existing summary/metrics changed'
    assert result['walking_summary']['event_audit']==original['walking_summary']['event_audit']
    old_result=dict(result,walking_summary=unchanged);assert old_result==original,'Report fields changed outside additive footfalls'
    assert actual.touch_count==12
    assert len(actual.export_frames)==original['report_config_snapshot']['raw_buffer']['retained_frames']
    output.mkdir(parents=True,exist_ok=False)
    evidence=dict(complete=True,recognized_steps=12,footfalls=12,valid_step_relationships=7,cycles=4,existing_summary_exact=True,existing_report_exact=True,raw_frames_preserved=len(actual.export_frames),original_report_sha256=hashlib.sha256((folder/'client/actor/report.json').read_bytes()).hexdigest(),footfall_mapping=s['footfalls'],physical_devices_opened=False,human_test_started=False)
    (output/'regression.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in evidence.items() if k!='footfall_mapping'}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();main(args.input,args.output)
