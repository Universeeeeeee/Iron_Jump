import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((ROOT/'experiments/slow_state_spacing/plan01.json').read_text())
    p.pop('schedule');p.pop('spacing_rules');p.pop('decision')
    p['cases']=['service01','interactive01','interactive02','service02'];p['case_variants']={n:'serial' for n in p['cases']}
    p['expected_session']={n:1 if n.startswith('interactive') else 0 for n in p['cases']}
    p['budget']='Exactly4 fixed-work windows, S4U/Interactive/Interactive/S4U. Stop at any task/runtime/semantics failure; no retries orreplacement. Task priority7 andQt offscreen common.'
    p['interpretation']='Session alone is qualified only if actual process priority, process/thread policy andQt backend match. S4U/Interactive also changes logon context; do not claim physical frequency orunique session mechanism.'
    p['condition_gate']='Both observed service contexts slow andboth interactive contexts fast with full work identity/cleanup/context checks supports this launch-context condition. Anything else leaves cause unknown. No optional extension.'
    p['dependency_sources']['experiments/qos_context_review/read_context.py']=sha(ROOT/'experiments/qos_context_review/read_context.py')
    p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1','.json') and f.name in ('entry.py','workload.py','verify.py','classify.py','spacing.py','reference01.json','worker.ps1','cohort.ps1','process_helper.ps1','freeze.py','preflight.py')}
    p['goal']='Test actual Windows launch/logon context with common fixed workload; no formal application optimization.'
    with (HERE/'plan01.json').open('x') as f:json.dump(p,f,indent=2)
    print('Frozen4launch-contextwindows;no prioritysetter ornewcomputeprimer')
