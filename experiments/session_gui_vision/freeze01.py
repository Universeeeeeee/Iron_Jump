"""Freeze one new semantic window; inherited evidence and gates remain immutable."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads((HERE.parent/'session_gui_proxy/plan01.json').read_text())
for key in ('sources','budget','qualification','limits'):p.pop(key)
for folder in ('session_gui_proxy','consumer_session_delivery','gil_workload_finalization','ground_throughput_diagnosis','gil_observation_termination'):
    for f in (HERE.parent/folder).glob('*.py'):p['existing_sources'][str(f.relative_to(ROOT))]=sha(f)
p['budget']='Exactly one saved-input full GUI/vision/original Python SDK with simulated native hardware, measurement child semantic delivery. No performance AB or physical devices.'
p['qualification']='Complete original raw/report/state, every active publication painted, actual decoded video/model/SDK work, real SDKready handshake, two source clock revisions, six QPC anchors within unchanged 1ms brackets, all resources closed. No performance qualification.'
p['limits']=['Dynamic latest-only video/model frame selection retained, not posthoc work-matched.','No physical camera/USB/human/Run; no formal edits.','Original application-return unconfirmed model cleanup retained even if observer tail later succeeds.','No GIL share, field fix or latency causality inference.']
p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1')}
with (HERE/'plan01.json').open('x') as out:json.dump(p,out,indent=2)
print('Frozen',len(p['sources']),'new sources;',len(p['existing_sources']),'existing sources')
