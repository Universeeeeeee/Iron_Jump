import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((ROOT/'experiments/label_call_identity/plan02.json').read_text())
    p.pop('native_entry');p.pop('profile_call_budget')
    p['cases']=[dict(id='safety01',backend='original',group='preview_bridge_safety_only')]
    p['budget']='Exactly one saved-source GUI with real model and existing simulated nativeSDK. No retry or latency/performance comparison.'
    p['qualification']='Full raw/report/runtime equality, original model/SDK protocol/finalization gates, bridge thread/instance/restore safety. Not real native SDK qualification.'
    p['prerequisite_review_sha256']=sha(ROOT/'experiments/canvas_bridge_semantics/review01.json')
    p['limits']=['No live camera/optical input orhuman/Run.','Only preview protected base-call changes; added safety counters are not accepted as a performance A/B fixture.','Real native SDK and complete callback/lifecycle qualification remain a separate prerequisite for causal AB.','Any fault stops this fixed budget; old failures and severe baseline reproduction gates unchanged.']
    for name in ('experiments/canvas_bridge_semantics/derive.py','experiments/qt_label_valid_paint_control/bridge.py','experiments/qt_label_valid_paint_control/binding_review01.json'):
        p['existing_sources'][name]=sha(ROOT/name)
    p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1','.diff')}
    with (HERE/'plan01.json').open('x') as f:json.dump(p,f,indent=2)
    print('Frozen one bridge safety window; fake native SDK explicitly retained')
