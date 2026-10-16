"""Post-experiment independent archive/snapshot checks; never imported by GUI."""
import hashlib,json,math
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    frozen=read(HERE/'frozen_sources.json');assert all(sha(ROOT/n)==v for n,v in frozen['files'].items())
    checked=[];rows_checked=0
    for folder in sorted((HERE/'runs').glob('pair_*')):
        pair=read(folder/'pair.json');assert pair['frozen_sources_sha256']==sha(HERE/'frozen_sources.json')
        assert read(folder/'complete.json')['system_exit_code']==0
        for name in ('cold','warm'):
            p=folder/name;m=read(p/'measurement.json');report=read(p/'report.json')
            assert all(v==sha(HERE/n) for n,v in m['source_hashes'].items())
            assert m['renderer_file'].replace('\\','/').endswith('/ui/ground_track.py')
            snapshots=sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0]);previous=(-1,-1)
            for r in snapshots+[m['queue_final']]:
                host,done,receipt,pending,oldest,latest,latest_receipt,unfinished,popped,phase,first,last,size=r
                assert done>=previous[0] and latest>=previous[1] and latest>=done
                assert unfinished==latest-done and popped==unfinished-pending and pending>=0 and popped>=0
                assert 0<receipt<=host and 0<latest_receipt<=host
                assert (oldest is None)==(pending==0)
                if oldest is not None:assert 0<oldest<=host
                if phase=='batch':assert first<=last<=latest and size==last-first+1
                previous=(done,latest);rows_checked+=1
            with np.load(p/'raw_archive.npz') as a:
                bits=a['bits'];times=a['device_timestamps'];ticks=[round(float(v)*1000) for v in times]
                assert bits.dtype==np.uint8 and bits.shape==(m['raw_total'],768) and np.all((bits==0)|(bits==1))
                assert all(b==a+1 for a,b in zip(ticks,ticks[1:]))
                assert ticks[-1]==m['queue_final'][1]==m['queue_final'][5]
                assert m['queue_final'][3]==m['queue_final'][7]==0
                assert hashlib.sha256(bits.tobytes()).hexdigest()==m['state']['raw_archive_sha256']
            assert isinstance(m['state']['quality'],dict) and report['finish_reason']=='manual'
            assert isinstance(report['report_config_snapshot'],dict)
            checked.append({'name':folder.name+'/'+name,'frames':len(ticks),'snapshots':len(snapshots)+1,'raw_sha256':sha(p/'raw_archive.npz'),'measurement_sha256':sha(p/'measurement.json'),'report_sha256':sha(p/'report.json')})
    assert len(checked)==12
    files={str(p.relative_to(HERE)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted([*(HERE/'runs').rglob('*'),*HERE.glob('*.log')]) if p.is_file()}
    (HERE/'evidence_manifest.json').write_text(json.dumps({'files':files},indent=2)+'\n')
    maximum_difference=[0.]
    def compare(a,b):
        if isinstance(a,dict):
            assert a.keys()==b.keys()
            for k in a:compare(a[k],b[k])
        elif isinstance(a,list):
            assert len(a)==len(b)
            for x,y in zip(a,b):compare(x,y)
        elif isinstance(a,float):
            maximum_difference[0]=max(maximum_difference[0],abs(a-b))
            assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8)
        else:assert a==b
    compare(read(HERE/'results.json'),read(HERE/'results_windows.json'))
    output={'mac_windows_offline_analysis_agree':True,'max_numeric_difference':maximum_difference[0],'formal_phases':checked,'snapshots_verified':rows_checked,'frozen_runtime_sources_match':True,'all_raw_bits_binary_and_device_ticks_contiguous':True,'all_final_queues_drained':True,'full_report_and_quality_preserved':True,'manifest_files':len(files),'wire_capture_present':False,'deterministic_live_AB_equivalence_claimed':False}
    (HERE/'verification.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps({k:v for k,v in output.items() if k!='formal_phases'},indent=2))
if __name__=='__main__':main()
