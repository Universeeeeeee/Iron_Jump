import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((ROOT/'experiments/preview_native_sdk/plan01.json').read_text())
    safety=ROOT/'experiments/preview_native_sdk/review01.json'
    assert json.loads(safety.read_text())['real_native_SDK_safety_window_pass']
    p['safety_prerequisite_sha256']=sha(safety);p['cases']=[];p['pairs']=[]
    for i,order in enumerate((('original','bridge'),('bridge','original'),('original','bridge'),('bridge','original')),1):
        pair={mode:f'pair{i:02d}_{mode}' for mode in ('original','bridge')};p['pairs'].append(pair)
        p['cases'] += [dict(id=pair[mode],backend='original',boundary=mode,pair=i) for mode in order]
    p['decision']=dict(input_lateness_max_ms=100,severe_observed_queue_at_least=1000,severe_scheduled_latency_at_least_ms=1000,
        minimum_severe_original_windows=3,candidate_queue_upper_max=250,candidate_scheduled_latency_max_ms=250,
        minimum_severe_pair_latency_reduction=.5)
    p['budget']='One fixed cohort:4 balanced original/bridge pairs,8 windows. No optional repeats, replacements orextension. Any infrastructure/semantic/nativeSDK failure stops remaining windows, all evidence retained.'
    p['qualification']='Original baseline keeps original AnnotationCanvas method. Candidate changes its first protected base-call only. Complete input/report/state/model/nativeSDK/context andcleanup checks in every window.'
    p['limits']=['Single base-call replacement includes the already safety-verified ABI bridge; no scaling, warmup, thread, processQoS orpipeline policy change.',
        'Both arms construct and validate the same bridge once. No candidate-only runtime safety wrapper orprofile hook.',
        'Same common pipeline/SDK audit on both arms, not certified zero-overhead3%/1%. No CPU/GIL time attribution.',
        'Fewer than3/4 severe original windows makes severe-symptom benefit unidentifiable. Never substitute fast-state benefit oradd windows.',
        'Retain dynamic input selection semantics, pose latest-only, GUI coalescing andSDK decisions; do not force identical selected model frames by changing policy.',
        'A positive symptom result is not a deployment orclinical1000Hz qualification.']
    for n in ('experiments/session_gui_comparison/metrics.py','experiments/preview_native_sdk/native_worker.py'):
        p['existing_sources'][n]=sha(ROOT/n)
    p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1','.diff')}
    p['performance_AB']=True;p['process_budget']=8;p['base_commit']='cfbb3b0b31f2294835ac909778643abf67e83f91'
    with (HERE/'plan01.json').open('x') as f:json.dump(p,f,indent=2)
    print('Frozen4pairs/8windows,3of4severe baseline required;nooptionalextension')
