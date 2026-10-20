import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((ROOT/'experiments/preview_bridge_delivery/plan01.json').read_text())
    proof=json.loads((ROOT/'experiments/preview_bridge_delivery/review01.json').read_text());assert proof['saved_GUI_safety_pass']
    p['prior_saved_model_safety_sha256']=sha(ROOT/'experiments/preview_bridge_delivery/review01.json')
    p['cases']=[dict(id='native_safety01',backend='original',group='preview_bridge_real_SDK_safety')]
    p['budget']='Exactly one saved input GUI safety window with original real native SDK and bridge; no retry, throughput AB orbaseline selection.'
    p['qualification']='Original raw/report/state, real model and SDK replies, actual loaded matchingSDK DLLs, stop/close, bridge safety and final process exit.'
    p['limits']=['Real camera control/gimbal can move according to original saved-pose tracking. No physical image oroptical acquisition.','Passive real SDK wrappers preserve exact returns/exceptions; this is a safety fixture, not performance instrumentation.','No severe baseline/benefit assessment; only next frozen AB may evaluate that under its reproduction gate.']
    baseline=json.loads((ROOT/p['formal_baseline_manifest']).read_text())
    for n in ('camera/bin/libdev.dll','camera/bin/obsbot_c_api.dll'):p['existing_sources'][n]=baseline['dependencies'][n]
    for n in ('experiments/preview_bridge_delivery/install.py',):p['existing_sources'][n]=sha(ROOT/n)
    p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1','.diff')}
    p['real_native_SDK']=True;p['performance_AB']=False;p['process_budget']=1
    with (HERE/'plan01.json').open('x') as f:json.dump(p,f,indent=2)
    print('Frozen one realSDK safety window; no performance AB')
