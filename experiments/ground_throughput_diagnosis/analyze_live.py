"""Verify field bytes and independent synchronous report before phase metrics."""
import argparse,hashlib,json,sys,time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from analyze import stats,digest

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))

def main(folder):
    from qtpy.QtCore import QCoreApplication
    from engine.gait_engine import GaitEngine
    from engine.device_quality_session import DeviceQualitySession
    from config.walking_config import WalkingConfig
    from config.overground_running_config import OvergroundRunningConfig
    from hardware.beam_quality import BeamQualityPolicy
    from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame,AcquisitionIssue
    app=QCoreApplication.instance() or QCoreApplication([])
    timing=read(folder/'timing.json');diag=read(folder/'diagnostic.json')
    assert timing['finished'] and not timing['errors']
    baseline=read(ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert diag['baseline_hashes']==baseline
    assert diag['thread_ids']['consumer']==diag['thread_ids']['measurement']!=diag['thread_ids']['gui']
    assert diag['probe_sha256']==hashlib.sha256((HERE/'live_probe.py').read_bytes()).hexdigest()
    report=read(folder/'report.json');meta=report['report_config_snapshot'];device=meta['device']
    ev=read(folder/'acquisition_evidence.json');delivery=read(folder/'live_delivery.json')
    assert delivery['system_exit_code']==0
    assert any(e.get('action')=='tracking_start' and e['result']==0 for e in delivery['sdk_events'])
    assert delivery['pose_draws']['with_valid_links']>0
    obs=read(folder/'camera_observations.json');armed=read(folder/'armed.json')['host_ns']
    active=[o for o in obs if o['running'] and o['host_ns']>=armed]
    assert active and all(o['sdk_tracking'] and o['sdk_start_confirmed'] and o['show_pose_checked'] and o['preview'] for o in active)
    raw={k:v for k,v in np.load(folder/'raw_frames.npz').items()}
    indices=raw['sample_indices'];received=raw['received_ns']
    assert len(indices)==len(ev['frames'])
    layouts={key:DeviceLayout(tuple(SensorSegment(**s) for s in v['segments']),tuple(v['invalid_bit_indices'])) for key,v in ev['layouts'].items()}
    for k,n in enumerate(indices):
        layout=layouts[ev['frames'][k]['stream_id']]
        assert layout.contact_bits(raw['wire'][k].tobytes())==raw['bits'][k].tobytes()
        if k:
            assert (int(raw['frame_indices'][k])-int(raw['frame_indices'][k-1]))%(2**32)==int(indices[k]-indices[k-1])
            assert int(indices[k]-indices[k-1])==int(raw['dropped_frames_before'][k])+1
    cfg_cls=WalkingConfig if timing['mode']=='walk' else OvergroundRunningConfig
    cfg=cfg_cls(**{k:v for k,v in meta.items() if k in cfg_cls.__dataclass_fields__ and cfg_cls.__dataclass_fields__[k].init})
    engine=GaitEngine(config=cfg);quality=DeviceQualitySession(cfg,BeamQualityPolicy(**meta['beam_quality']['preflight']['policy']),engine)
    engine.quality=quality;quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
    start=int(np.searchsorted(indices,device['checked_sample_index'],side='right'))
    budget=meta['raw_buffer'];end=start+budget['total_received_frames'];processed_end=end-budget['raw_only_tail_frames']
    assert end<=len(indices) and not budget['truncated']
    assert int(indices[start-1])==device['checked_sample_index']
    assert int(received[start-1])==device['checked_monotonic_ns']
    clock=[int(received[0])];original_clock=time.perf_counter_ns
    time.perf_counter_ns=lambda:clock[0]
    try:
        for kind,index in ev['events']:
            if kind=='issue':
                item=ev['issues'][index];quality.on_issue(AcquisitionIssue(item['code'],item['frame_index'],tuple(item['missing_wire_segments'])))
                continue
            if index>=end:break
            if index==processed_end:quality.halt()
            info=ev['frames'][index];clock[0]=int(received[index])
            frame=SensorFrame(info['stream_id'],layouts[info['stream_id']],int(raw['frame_indices'][index]),int(indices[index]),clock[0],raw['bits'][index].tobytes(),raw['valid_bits'][index].tobytes(),raw['wire'][index].tobytes(),int(raw['dropped_frames_before'][index]),tuple(info['quality_flags']))
            quality.on_frame(frame)
            if index==start-1:
                quality.arm_checked((quality._status()['device_key'],meta['beam_quality']['empty_field_acknowledged']))
                assert quality.context is not None
        quality.halt();engine.overground.halt()
        replay=asdict(engine.build_report(report['finish_reason']))
    finally:time.perf_counter_ns=original_clock
    replay.pop('export_frames',None);replay.pop('export_timestamps',None)
    (folder/'independent_report.json').write_text(json.dumps(replay,ensure_ascii=False),encoding='utf-8')
    replay=json.loads(json.dumps(replay))
    assert replay==report,'Independent full report differs; performance is not accepted'
    assert json.loads(json.dumps(quality.snapshot()))==diag['final_state']['quality']
    runtime=quality._runtime;window=hashlib.sha256()
    for bits,changes in runtime._window:window.update(bits.tobytes());window.update(changes.tobytes())
    for key,value in [('runtime_counts',runtime._counts.tolist()),('runtime_transitions',runtime._transitions.tolist()),('runtime_healthy_samples',runtime.healthy_samples),('runtime_window_sha256',window.hexdigest())]:assert diag['final_state'][key]==value
    assert diag['final_state']['processor_audit_sha256']==digest(engine.overground.processor.event_audit)
    masked=raw['bits'].copy();masked[:,device['bad_indices']]=0
    occupancy=np.any(masked,axis=1)
    phases=[]
    last_sample=int(indices[end-1]);checked=device['checked_sample_index']
    for begin in range(checked+1,last_sample+1,1000):
        stop=min(begin+1000,last_sample+1);sel=(indices>=begin)&(indices<stop)
        ratio=float(np.mean(occupancy[sel]))
        label='dense' if ratio>=.5 else 'empty' if ratio<=.01 else 'mixed'
        phases.append({'start':begin,'end':stop,'occupancy_fraction':ratio,'phase':label})
    groups=[]
    for phase in phases:
        if groups and groups[-1]['phase']==phase['phase'] and groups[-1]['end']==phase['start']:groups[-1]['end']=phase['end']
        else:groups.append({k:phase[k] for k in ('start','end','phase')})
    for group in groups:
        points=[p for p in diag['milestones'] if group['start']<=p[1]<group['end']]
        sample_mask=(indices>=group['start'])&(indices<group['end']);positions=np.flatnonzero(sample_mask)
        group['frames_received']=len(positions)
        if len(points)>1:
            ages=[(p[0]-p[2])/1e6 for p in points]
            group.update(consumer_fps=(points[-1][1]-points[0][1])*1e9/(points[-1][0]-points[0][0]),age_slope_ms_per_device_second=float(np.polyfit([(p[1]-points[0][1])/1000 for p in points],ages,1)[0]),completion_age_ms=stats(ages))
        if len(positions)>1:group['source_arrival_fps']=(len(positions)-1)*1e9/(received[positions[-1]]-received[positions[0]])
    decisions=[e['tracking_event'] for e in delivery['sdk_events'] if e.get('tracking_event',{}).get('event')=='tracking_decision']
    sdk_calls=[e['tracking_event'] for e in delivery['sdk_events'] if e.get('tracking_event',{}).get('event')=='sdk_call']
    sdk_proof={'tracking_decisions':len(decisions),'decision_reasons':dict(Counter(d['reason'] for d in decisions)), 'set_speed_calls':sum(e['method']=='set_speed' for e in sdk_calls), 'nonzero_set_speed_calls':sum(e['method']=='set_speed' and any(e['args']) for e in sdk_calls), 'errors':[e for e in delivery['sdk_events'] if 'error' in e]}
    processor=engine.overground.processor
    component='walking_summary' if timing['mode']=='walk' else 'running_summary'
    count_evidence={'physical_count_from_user_filename':10 if timing['mode']=='walk' else 8, 'first_foot_from_user':'Right', 'confirmed_contacts':report[component]['confirmed_contacts'],'valid_touches':report[component]['valid_touches'],'valid_steps':report[component]['valid_steps'],'semantics':'valid_steps counts admitted step-time intervals; valid_touches counts reliable touch events, neither is automatically physical footfalls.'}
    if timing['mode']=='walk':
        confirmed=[c for c in processor.contacts if c.confirmed]
        admitted={(x['from_id'],x['to_id']) for x in report[component]['steps']}
        barriers=[(a/1000,b/1000,{'kind':'ownership','epoch':epoch}) for a,b,epoch in processor._ownership_barriers()]
        barriers += [(a,b,{'kind':'narrow_candidate'}) for a,b in processor._narrow_barriers]
        omitted=[]
        for a,b in zip(confirmed,confirmed[1:]):
            if (a.id,b.id) in admitted:continue
            omitted.append({'from_id':a.id,'to_id':b.id,'endpoint_touch_known':[a.touch_known,b.touch_known],'endpoint_labels':[a.label,b.label], 'intervening_unresolved_contact_ids':[c.id for c in processor.contacts if a.start<c.start<b.start and c.candidate_outcome not in {'excluded_nonstep','associated_fragment'}], 'overlapping_barriers':[{'start_sample':round(left*1000),'end_sample':round(right*1000),'source':reason} for left,right,reason in barriers if a.start<right and b.start>left]})
        count_evidence['omitted_adjacent_confirmed_pairs']=omitted
        count_evidence['confirmed_without_reliable_touch']=[{'id':c.id,'confirmed_sample':round(c.confirmed_at*1000),'exclusion':c.exclusion,'touch_known':c.touch_known,'candidate_outcome':c.candidate_outcome} for c in confirmed if not c.touch_known]
    else:
        count_evidence['invalid_step_time_pairs']=[{'from_id':x['from_id'],'to_id':x['to_id'],'time_s':x['time_s']} for x in report[component]['steps'] if not x['time_s']['valid']]
    output={'name':folder.name,'mode':timing['mode'],'raw_frames':len(indices),'accepted_after_arm':budget,'raw_wire_counter_validity_issue_sidecars_verified':True,'full_report_and_runtime_quality_audit_exact':True,'canonical_report_sha256':digest(report),'physical_scanout_measured':False,'count_evidence':count_evidence,'sdk_start_success':True,'sdk_success_and_preview_enabled_during_active_status_samples':len(active),'sdk_events':len(delivery['sdk_events']),'sdk_proof':sdk_proof,'pose_draws':delivery['pose_draws'],'camera_record_end':read(folder/'camera_record_end.json'),'receipt_to_paint_ms':timing['received_to_paint_ms'],'phases':phases,'phase_groups':groups,'source_limits':'One physical pass; M plus SDK/draw evidence observers not separately calibrated; no causal partition or statistical 1000Hz guarantee. Latency ends at Qt paint completion and starts at host USB receipt.'}
    (HERE/(folder.name+'_summary.json')).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);main(p.parse_args().folder)
