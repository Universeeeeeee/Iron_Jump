"""Offline integrity checks; no imports from or callbacks into the live program."""
import csv,hashlib,json
from pathlib import Path
import numpy as np

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def verify(folder):
    m=read(folder/'measurement.json');s=read(folder/'state.json');r=read(folder/'report.json');a=read(folder/'acquisition.json');shutdown=read(folder/'shutdown.json')
    assert read(folder/'complete.json')=={'system_exit_code':0,'serialized':True}
    assert not m['errors'] and not m['SDK_errors'] and not shutdown['errors'] and not shutdown['readers'] and shutdown['SDK']['stops']>0
    assert m['frozen_sources_sha256']==sha(folder.parent.parent/'frozen_sources.json')
    assert m['renderer_file'].replace('\\','/').endswith('/ui/ground_track.py')
    assert r['finish_reason']=='manual'
    assert len(m['readers_at_start'])==1 and not m['readers_after_stop'] and m['threads']['gui']!=m['threads']['consumer']
    assert m['queue_final'][3]==m['queue_final'][7]==0
    points=sorted(m['queue_common']+m['queue_samples'],key=lambda row:row[0])+[m['queue_final']]
    previous=(-1,-1)
    for row in points:
        host,done,receipt,pending,oldest,latest,latest_receipt,unfinished,popped,phase,first,last,size=row
        assert done>=previous[0] and latest>=previous[1] and latest>=done
        assert unfinished==latest-done and popped==unfinished-pending and pending>=0 and popped>=0
        assert (oldest is None)==(pending==0)
        if oldest is not None:assert 0<oldest<=host
        if phase=='batch':assert first<=last<=latest and size==last-first+1
        previous=(done,latest)
    with np.load(folder/'raw_frames.npz') as z:raw={k:z[k] for k in z.files}
    with np.load(folder/'raw_archive.npz') as z:bits=z['bits'];ticks=np.rint(z['device_timestamps']*1000).astype(np.int64)
    samples=raw['sample_indices'];idx=np.searchsorted(samples,ticks)
    assert np.all(np.diff(samples)==1) and np.all(np.diff(ticks)==1) and np.array_equal(samples[idx],ticks)
    assert np.all(np.diff(raw['frame_indices'])==1) and np.all(raw['dropped_frames_before']==0) and np.all(np.diff(raw['received_ns'])>=0)
    assert len(bits)==m['raw_total']==m['raw_retained'] and np.array_equal(raw['bits'][idx],bits)
    assert hashlib.sha256(bits.tobytes()).hexdigest()==m['raw_archive_sha256']
    assert ticks[-1]==m['queue_final'][1]==m['queue_final'][5]
    assert not a['issues'] and a['events']==[['frame',int(n)] for n in samples]
    assert len(a['frames'])==len(samples) and len(a['layouts'])==1
    layout=next(iter(a['layouts'].values()));decoded=np.empty_like(raw['bits'])
    for i,seg in enumerate(layout['segments']):
        offset=12*seg['wire_index'];v=1-np.unpackbits(raw['wire'][:,offset:offset+12],axis=1,bitorder='little')
        decoded[:,i*96:(i+1)*96]=v[:,::-1] if seg['reversed'] else v
    assert np.array_equal(decoded,raw['bits']) and np.all(raw['valid_bits']==1)
    assert not any(frame['quality_flags'] for frame in a['frames'])
    summary=r['walking_summary' if m['mode']=='walk' else 'running_summary']
    assert summary['event_audit']==s['audit'] and r['report_config_snapshot']['beam_quality']==s['quality']
    assert not s['quality']['events_truncated'] and s['quality']['event_count']==len(s['quality']['events'])
    # Production _quality_report masks preflight bad bits in visual history only.
    timeline=json.loads(json.dumps(s['timeline']));bad=s['quality']['preflight']['bad_indices']
    for frame in timeline:
        for bit in bad:frame['valid_bits'][bit]=0
    assert timeline==r['visual_timeline']
    with (folder/'camera.csv').open() as f:camera=list(csv.DictReader(f))
    lengths=[int(x['length']) for x in camera];offsets=[int(x['offset']) for x in camera]
    end=read(folder/'camera_record_end.json')['stats']
    assert offsets[0]==0 and all(b==a+n for a,n,b in zip(offsets,lengths,offsets[1:]))
    assert len(camera)==end['frames_written'] and sum(lengths)==end['bytes_written']
    assert end['frames_dropped']==end['queued_frames']==end['queued_bytes']==end['recording']==0 and end['last_hresult']>=0
    formal=(raw['received_ns'][idx]>=m['armed_ns'])&(raw['received_ns'][idx]<m['stop_request_ns'])
    usable=bits.copy();usable[:,bad]=0
    pubs=[v for v in summary['event_publications'] if v.get('active')]
    return {'name':folder.name,'mode':m['mode'],'integrity_passed':True,'queue_invariant_snapshots':len(points),'raw_frames_with_preparation':len(samples),'formal_archived_frames':len(bits),'formal_usable_contact_fraction':float(np.any(usable[formal],axis=1).mean()),'device_and_frame_counters_contiguous':True,'wire_decodes_to_retained_bits':True,'original_archive_equals_raw_sensorframes':True,'event_audit_equals_report':True,'quality_snapshot_equals_report':True,'quality_history_untruncated':True,'report_timeline_equals_original_quality_masked_history':True,'active_publications':len(pubs),'painted_contact_ids':len(m['paints']),'report_touch_count':r['touch_count'],'report_valid_steps':summary['valid_steps'],'camera_csv_contiguous':True,'native_video_bytes':end['bytes_written'],'native_video_frames':end['frames_written'],'one_reader_final_drained_sdk_stopped':True,'scope':'Integrity and original report transformation checks, not cross-run algorithm equivalence or observer-overhead calibration.'}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('--output',type=Path);args=p.parse_args();result=verify(args.folder)
    value=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(value,encoding='utf-8')
    else:print(value)
