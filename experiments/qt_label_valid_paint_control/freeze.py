"""Freeze a finite synthetic rendering-equivalence control, never performance."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    reference=json.loads((HERE/'reference_plan01.json').read_text())
    modules=dict(reference['exact_modules'])
    modules['D:/conda/Lib/site-packages/PySide6/Qt6Gui.dll']='cd071161ad325ff2de92b0e33d71334ef20712544796949623ce92dfb3957e90'
    assert all(sha(Path(n))==v for n,v in modules.items())
    names=['bridge.py','control.py','check.py','test_check.py','freeze.py','launch02.ps1','binding_review01.json','reference_plan01.json']
    cases=[dict(id='opaque_a',size=[233,151],seed=0,alpha=False,scaled=True,source_dpr=1,target_dpr=1),
        dict(id='opaque_b',size=[233,151],seed=1,alpha=False,scaled=True,source_dpr=1,target_dpr=1),
        dict(id='alpha_fractional',size=[257,173],seed=2,alpha=True,scaled=True,source_dpr=1,target_dpr=1.25),
        dict(id='source_and_target_fractional',size=[311,211],seed=3,alpha=True,scaled=True,source_dpr=1.5,target_dpr=1.5),
        dict(id='double_dpr',size=[337,219],seed=4,alpha=True,scaled=True,source_dpr=2,target_dpr=2),
        dict(id='unscaled',size=[239,157],seed=5,alpha=False,scaled=False,source_dpr=1,target_dpr=1)]
    plan=dict(base_commit='9cdae1868b82fa65dbdc013de0a8e2c2985db057',sources={n:sha(HERE/n) for n in names},
        exact_modules=modules,cases=cases,process_budget=1,retry_budget=0,maximum_valid_render_calls=24,
        invalid_argument_calls=8,None_helper_reference_calls=17,performance_endpoints=[],
        error_policy='Compare callback error location/identity with the unchanged binding reference; any pixel, ownership, cleanup, diagnostic or error-channel mismatch rejects this control.',
        performance_AB=False,formal_program_or_existing_paint_candidate_changed=False,field_attribution_ready=False,
        scope='One offscreen synthetic correctness process only. No saved/human Walk, device, SDK, model, CPU sampler, trace or performance experiment.')
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    print(json.dumps(plan,indent=2))
