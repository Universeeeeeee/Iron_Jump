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
        for name,value in m['sources'].items():assert frozen['experiments/gil_gui_calibration/'+name]==value
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
