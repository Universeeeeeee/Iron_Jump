"""Archive-only audit of the first OFF; preserve its failed normal-exit status."""
import csv,hashlib,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;CASE=HERE/'runs/20261017_110109_a6595b80_walk_off';P=CASE/'capture'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def main():
    m=read(P/'measurement.json');state=read(P/'state.json');report=read(P/'report.json');acq=read(P/'acquisition.json');end=read(P/'camera_record_end.json')['stats'];shutdown=read(P/'shutdown.json')
    with np.load(P/'raw_frames.npz') as z:raw={k:z[k] for k in z.files}
    with np.load(P/'raw_archive.npz') as z:bits=z['bits'];ticks=np.rint(z['device_timestamps']*1000).astype(np.int64)
    indices=np.searchsorted(raw['sample_indices'],ticks);decoded=np.empty_like(raw['bits']);layout=next(iter(acq['layouts'].values()))
    for i,seg in enumerate(layout['segments']):
        j=12*seg['wire_index'];block=1-np.unpackbits(raw['wire'][:,j:j+12],axis=1,bitorder='little');decoded[:,i*96:(i+1)*96]=block[:,::-1] if seg['reversed'] else block
    with (P/'camera.csv').open() as f:video=list(csv.DictReader(f))
    offsets=[int(v['offset']) for v in video];lengths=[int(v['length']) for v in video]
    checks={'counter_continuous':bool(np.all(np.diff(raw['sample_indices'])==1) and np.all(np.diff(raw['frame_indices'])==1) and np.all(np.diff(ticks)==1)),'no_reported_raw_drops_or_issues':bool(np.all(raw['dropped_frames_before']==0) and not acq['issues']),'wire_matches_retained_bits':np.array_equal(decoded,raw['bits']),'formal_archive_matches_raw':bool(np.array_equal(raw['sample_indices'][indices],ticks) and np.array_equal(bits,raw['bits'][indices]) and len(bits)==m['raw_total']==m['raw_retained']),'archive_sha_matches':hashlib.sha256(bits.tobytes()).hexdigest()==m['raw_archive_sha256'],'event_order_preserved':acq['events']==[['frame',int(n)] for n in raw['sample_indices']],'event_audit_matches_report':state['audit']==report['walking_summary']['event_audit'],'quality_history_matches_report':state['quality']==report['report_config_snapshot']['beam_quality'] and not state['quality']['events_truncated'],'queue_fully_drained':m['queue_final'][3]==m['queue_final'][7]==0,'SDK_closed_no_readers':shutdown['serialized'] and shutdown['SDK']['stops']>0 and not shutdown['errors'] and not shutdown['SDK_errors'] and not shutdown['readers'],'video_csv_complete':bool(offsets[0]==0 and all(b==a+n for a,n,b in zip(offsets,lengths,offsets[1:])) and len(video)==end['frames_written'] and sum(lengths)==end['bytes_written']),'video_writer_closed_no_drops':end['recording']==end['queued_frames']==end['queued_bytes']==end['frames_dropped']==0 and end['last_hresult']==0,'captured_source_hash_matches':m['frozen_sources_sha256']==hashlib.sha256((CASE/'sources_at_capture/frozen_sources.json').read_bytes()).hexdigest()}
    assert all(checks.values()),checks
    result={'case':CASE.name,'scope':'Archive integrity only; normal GUI exit failed. Original completion/report data are not rewritten.','checks':checks,'archive_checks_passed':True,'formal_frames':len(bits),'raw_frames_including_preparation':len(raw['sample_indices']),'duration_s':(m['stop_request_ns']-m['armed_ns'])/1e9,'video_frames':len(video),'video_bytes':end['bytes_written'],'report_touch_count':report['touch_count'],'normal_completion_marker_present':(P/'complete.json').exists(),'matched_load_calibration_baseline_accepted':False,'exclusion_reason':'Unbounded tail status changed GUI workload; self-close interception prevented normal completion. Retain as failure evidence; restart OFF after UI-only fix.'}
    (HERE/'field01_archive_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
