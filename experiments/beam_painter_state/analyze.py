"""Correctness before metrics; frozen A/A and benefit gates, no microbench gains."""
import copy,hashlib,json,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
CACHE={}
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def canonical(report,checked_ns=None):
    for d in (report['report_config_snapshot']['device'],report['report_config_snapshot']['beam_quality']['preflight']):
        if checked_ns is not None:assert d['checked_monotonic_ns']==checked_ns
        del d['checked_monotonic_ns']
    return report

def source(mode):
    if mode not in CACHE:
        folder=HERE/'inputs'/mode;report=read(folder/'report.json');meta=report['report_config_snapshot'];d=meta['device'];evidence=read(folder/'acquisition_evidence.json');assert not evidence['issues']
        with np.load(folder/'raw_frames.npz') as raw:
            first=int(np.searchsorted(raw['sample_indices'],d['checked_sample_index']-3500));checked=int(np.searchsorted(raw['sample_indices'],d['checked_sample_index']));end=checked+1+meta['raw_buffer']['total_received_frames'];data={k:raw[k][first:end].copy() for k in raw.files}
        CACHE[mode]={'data':data,'checked':d['checked_sample_index'],'bad':d['bad_indices'],'meta':evidence['frames'][first:end],'groups':read(HERE/'phases.json')[mode]}
    return CACHE[mode]

def verify(folder):
    assert hashlib.sha256((HERE/'plan.json').read_bytes()).hexdigest()==(HERE/'plan.sha256').read_text().split()[0]
    if (HERE/'frozen_sources.json').exists():
        frozen=read(HERE/'frozen_sources.json')['files']
        for rel,expected in frozen.items():assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==expected,rel
    m=read(folder/'measurement.json');mode=m['mode'];s=source(mode);data=s['data']
    assert read(folder/'complete.json')['system_exit_code']==0
    baseline=read(ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];assert m['baseline_hashes']==baseline
    assert m['renderer_sha256']==read(HERE/'plan.json')['renderer_sha256'][m['variant']]
    if (HERE/'frozen_sources.json').exists():
        for name,value in m['sources'].items():assert frozen['experiments/beam_painter_state/'+name]==value
    assert m['qt_platform']=='windows' and m['threads']['consumer']!=m['threads']['gui']
    assert not m['errors'] and not m['sdk_errors'] and m['sdk']['start_success'] and m['sdk']['tracking_decisions']>0 and m['sdk']['nonzero_speeds']>0
    assert m['pose_draws']['valid']>0 and m['pose_draws']['disabled_calls']==0 and m['camera']['decoded_frames']>0
    with np.load(folder/'raw_frames.npz') as delivered:
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(delivered[key],data[key]),(folder.name,key)
        received=delivered['received_ns'].copy()
        assert np.all(np.diff(received)>=0)
        assert np.array_equal(delivered['bits'],1-np.unpackbits(delivered['wire'],axis=1,bitorder='little'))
    assert m['delivered_metadata_sha256']==digest([[v['stream_id'],v['quality_flags'],int(data['dropped_frames_before'][k])] for k,v in enumerate(s['meta'])])
    checked_ns=int(received[3500]);report=read(folder/'report.json');normalized=canonical(copy.deepcopy(report),checked_ns)
    assert normalized==read(HERE/'oracles'/mode/'report.json'),(folder.name,'Full report mismatch')
    state=copy.deepcopy(m['state']);assert state['quality']['preflight']['checked_monotonic_ns']==checked_ns
    del state['quality']['preflight']['checked_monotonic_ns']
    assert state==read(HERE/'oracles'/mode/'state.json'),(folder.name,'Full quality/runtime/audit/archive state mismatch')
    events=report['walking_summary' if mode=='walk' else 'running_summary']['event_publications'];active=[e for e in events if e['active']]
    assert set(m['paints'])=={str(e['contact_id']) for e in active},'Missing/extra painted publication'
    assert m['source_indices']==[int(data['sample_indices'][0]),int(data['sample_indices'][-1])]
    assert m['arrivals'][-1][2]==int(data['sample_indices'][-1]) and len(m['arrivals'])==len(received)
    return m,s,report,received,active

def stats(values):return {'p50':float(np.median(values)),'p95':float(np.percentile(values,95)),'max':float(max(values))}

def metrics(folder,common=False):
    m,s,report,received,active=verify(folder);points=m['common'] if common or m['probe']=='L' else m['batches']
    indices=s['data']['sample_indices'];lookup=dict(zip(indices.tolist(),received.tolist()))
    latencies=[(m['paints'][str(e['contact_id'])]-lookup[e['touch_sample']])/1e6 for e in active]
    result={'name':folder.name,'mode':m['mode'],'variant':m['variant'],'probe':m['probe'],'observation':'common' if common else 'full_P','footprint_count':len(latencies),'footprint_p95_ms':float(np.percentile(latencies,95)),'footprint_max_ms':float(max(latencies)),'phases':[],'full_raw_report_quality_evidence_exact':True,'sdk':m['sdk'],'pose_draws':m['pose_draws'],'camera':m['camera'],'canonical_report_sha256':digest(canonical(copy.deepcopy(report)))}
    for group in s['groups']:
        p=[p for p in points if group['start']<=p[1]<group['end']]
        assert len(p)>2,(folder.name,group)
        ages=[(x[0]-x[2])/1e6 for x in p]
        result['phases'].append({**group,'consumer_fps':(p[-1][1]-p[0][1])*1e9/(p[-1][0]-p[0][0]),'age_slope_ms_per_device_second':float(np.polyfit([(x[1]-p[0][1])/1000 for x in p],ages,1)[0]),'completion_age_ms':stats(ages),'observations':len(p)})
    bits=s['data']['bits'].copy();bits[:,s['bad']]=0;contact=np.any(bits,axis=1)&(indices>s['checked']);last=int(indices[np.flatnonzero(contact)[-1]])
    due={n:t for _,t,n in m['arrivals']};recovery=None
    for index,p in enumerate(points):
        if p[1]<=last or (p[0]-p[2])>10000000:continue
        future=[x for x in points[index:] if x[1]<p[1]+500]
        if future and future[-1][1]-p[1]>=450 and all(x[0]-x[2]<=10000000 for x in future):recovery=(p[0]-due[last])/1e9;break
    result['recovery_s']=recovery;result['last_raw_usable_contact_sample']=last
    result['reader_scheduled_lag_ms']=stats([(a-b)/1e6 for a,b,n in m['arrivals'] if n>s['checked']])
    dense=next(g for g in result['phases'] if g['phase']=='dense')
    result['dense_fps']=dense['consumer_fps'];result['age_slope_ms_per_device_second']=dense['age_slope_ms_per_device_second']
    return result

def paired(left,right):
    return {'fps_fraction':right['dense_fps']/left['dense_fps']-1,'age_slope_ms_per_device_second':right['age_slope_ms_per_device_second']-left['age_slope_ms_per_device_second'],'footprint_p95_ms':right['footprint_p95_ms']-left['footprint_p95_ms'],'footprint_max_ms':right['footprint_max_ms']-left['footprint_max_ms'],'recovery_s':None if left['recovery_s'] is None or right['recovery_s'] is None else right['recovery_s']-left['recovery_s']}

def assess_calibration():
    plan=read(HERE/'plan.json');output={'modes':{},'scope':'Incremental P vs shared L, not proof of zero observer cost; intrinsic run variability can also make calibration fail.'}
    for mode in ('walk','run'):
        pairs=[];runs=[]
        for block in range(1,7):
            l=metrics(HERE/'runs'/f'aa_{mode}_{block:02d}_L',True);p=metrics(HERE/'runs'/f'aa_{mode}_{block:02d}_P',True);runs.extend([l,p]);pairs.append(paired(l,p))
        medians={key:None if any(p[key] is None for p in pairs) else float(np.median([p[key] for p in pairs])) for key in pairs[0]}
        limits={'fps_fraction':.03,'age_slope_ms_per_device_second':5,'footprint_p95_ms':25,'footprint_max_ms':25,'recovery_s':.15}
        # Check frozen plan values so editing thresholds cannot silently pass a run.
        assert list(limits.values())==list(plan['calibration']['limits'].values())
        passed=all(medians[k] is not None and abs(medians[k])<=limits[k] for k in limits)
        noise={key:None if any(p[key] is None for p in pairs) else float(np.percentile([abs(p[key]) for p in pairs],90)) for key in pairs[0]}
        output['modes'][mode]={'pass':passed,'paired_medians_P_minus_L':medians,'noise90_absolute':noise,'pairs':pairs,'runs':runs}
    return output

def write_calibration():
    result=assess_calibration();(HERE/'calibration.json').write_text(json.dumps(result,indent=2)+'\n');return result

def AB():
    calibration=read(HERE/'calibration.json');assert all(x['pass'] for x in calibration['modes'].values())
    output={}
    for mode in ('walk','run'):
        pairs=[];runs=[]
        for block in range(1,7):
            a=metrics(HERE/'runs'/f'ab_{mode}_{block:02d}_A');b=metrics(HERE/'runs'/f'ab_{mode}_{block:02d}_B');runs.extend([a,b]);pairs.append(paired(a,b))
        medians={k:None if any(p[k] is None for p in pairs) else float(np.median([p[k] for p in pairs])) for k in pairs[0]}
        regressions={'fps_fraction':.03,'age_slope_ms_per_device_second':5,'footprint_p95_ms':25,'footprint_max_ms':25,'recovery_s':.15}
        no_regression=all(medians[k] is not None and ((-medians[k] if k=='fps_fraction' else medians[k])<=limit) for k,limit in regressions.items())
        gains={}
        for key,minimum in [('fps_fraction',.05),('age_slope_ms_per_device_second',10),('footprint_p95_ms',25)]:
            sign=1 if key=='fps_fraction' else -1;values=[sign*p[key] for p in pairs];noise=calibration['modes'][mode]['noise90_absolute'][key]
            gains[key]={'median_gain':float(np.median(values)),'minimum':minimum,'noise90':noise,'all_six_positive':all(v>0 for v in values),'passes':all(v>0 for v in values) and np.median(values)>max(minimum,noise)}
        output[mode]={'runs':runs,'pairs_B_minus_A':pairs,'paired_medians':medians,'no_material_regression':no_regression,'gains':gains,'recommend':no_regression and any(g['passes'] for g in gains.values())}
    (HERE/'AB.json').write_text(json.dumps(output,indent=2)+'\n');return output

if __name__=='__main__':
    if sys.argv[1]=='calibration':print(json.dumps(write_calibration(),indent=2))
    elif sys.argv[1]=='AB':print(json.dumps(AB(),indent=2))
    else:
        for mode in ('walk','run'):print(json.dumps(metrics(HERE/'runs'/('smoke_'+mode)),indent=2))
