"""One baseline semantic window through the shared GUI body; no performance comparison."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads((HERE.parent/'session_gui_vision/plan02.json').read_text())
for k in ('sources','previous_failed_window'):p.pop(k,None)
for name in ('clocks.py','links.py','fake_sdk.py','draw02.py','client.py','state.py','inbox.py','actor.py','outbox.py','commands.py','json_values.py'):
 f=HERE.parent/'session_gui_vision'/name;p['existing_sources'][str(f.relative_to(ROOT))]=sha(f)
p['backend']='original';p['budget']='Exactly one saved-source original same-process semantic window with shared GUI body, real model and original SDK Python runtime with simulated native backend. No performanceAB or physical hardware.'
p['qualification']='Complete original raw/report/state; original controller in GUI and original measurement QThread, no measurementIPC, all active publicationIDs painted, real model/SDK work and final resource cleanup. All six role clock anchors pass unchanged1ms bracket; GUI/measurement intentionally samePID.'
p['limits']=['Only an experimental saved-input facade, not a formal program change.','No matched effect orAA variance/observer-disturbance pass; historical windows cannot form a pair.','Original-return model cleanup remains separate from bounded observer tail.']
p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1')}
with (HERE/'plan01.json').open('x') as f:json.dump(p,f,indent=2)
print(len(p['sources']),len(p['existing_sources']))
