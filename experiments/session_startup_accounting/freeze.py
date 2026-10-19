"""Four default GUI passive-observation windows; no active CPU probe or candidate."""
import ast,hashlib,json,zipfile
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads((HERE.parent/'session_gui_comparison/plan02.json').read_text());p.pop('aa_cases');p.pop('pairs');p['cases']=[dict(id=f'startup{i:02d}',backend='original',group='passive_observation') for i in range(1,5)]
for folder,names in [('session_gui_comparison',('context.py','local_failure.py','metrics.py')),('fixed_work_accounting',('counters.py',))]:
 for name in names:
  f=ROOT/'experiments'/folder/name;p['existing_sources'][str(f.relative_to(ROOT))]=sha(f)
p['formal_baseline_manifest']='experiments/gil_gui_analysis/stack_plan01.json';p['formal_baseline_manifest_sha256']=sha(ROOT/p['formal_baseline_manifest'])
p['native_readiness']={n:sha(HERE/n) for n in ('native_check01.json','native_contract02.json','snapshot_preparation02.json')}
p['native_preparation_archive_sha256']=sha(HERE/'native_preparation01.zip')
p['budget']='Exactly four original same-process sharedGUI windows. No candidate, power/priority/QoS/affinity/GC changes, native compute primer, human/USB/Run oroptional extension. Stop after any infrastructure/semantic/CPU-ledger failure.'
p['qualification']='Original complete raw/report/state, real model/SDK work and final resources; six original phase contexts, twelveCPU reads each1ms bracket, return/exception preserved. Old3%/1% and native-stack failures remain.'
p['state_labels']=dict(slow_base_adapter_ms_at_least=30.0,fast_base_adapter_ms_at_most=26.0,scope='Exploratory preregistered precontact timing proxies from prior cohort; not perturbation, stackclosure orclinical gates.')
source=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz';assert sha(source)==p['input_sha256']['raw_frames.npz']
ref=json.loads((ROOT/'experiments/session_gui_comparison/runs/evidence01/runs/cohort01/aa01/capture/client/actor/report.json').read_text());touch=min(v['touch_sample'] for v in ref['walking_summary']['event_publications'] if v['active']);p['first_touch_sample']=touch
with np.load(source) as z:
 first=int(np.searchsorted(z['sample_indices'],p['checked_sample']-3500));i=int(np.searchsorted(z['sample_indices'],touch));p['first_touch_offset_ns']=int(z['received_ns'][i])-int(z['received_ns'][first])
p['limits']=['Read-only counters held underGIL per shortWin32 call to avoid addingFFI release/reacquire waits; fullcapture cost is measured, not claimed zero.','Thread/process snapshots are bounded, not simultaneous; processCPU includes nativeworkers and consumer/GUI work.','No actualGHz, instruction-count orGIL share inferred; no active benchmark ornewperformanceAB.','No root cause orformalfix qualification even if ledger reads pass.']
p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1')}
with (HERE/'plan01.json').open('x') as f:json.dump(p,f,indent=2)
print('Frozen',len(p['sources']),'sources;',len(p['existing_sources']),'dependencies;4 windows')
