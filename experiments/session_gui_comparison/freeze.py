"""Fixed four A/A + four counterbalanced AB pairs, with unchanged symptom gates."""
import hashlib,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads((HERE.parent/'session_local_baseline/plan01.json').read_text());p.pop('backend');p.pop('sources')
for folder,names in [('session_local_baseline',('gui.py','local.py','pipeline_review.py')),('session_gui_vision',('verify_pipeline02.py',)),('gui_qos_candidate',('runtime_context.py','decision.py')),('session_isolation_throughput',('analyze01.py',)),('gil_gui_analysis',('temporal_review02.py','publication_map02.json')),('gil_observation_termination',('queue_bounds.py',))]:
 for n in names:
  f=ROOT/'experiments'/folder/n;p['existing_sources'][str(f.relative_to(ROOT))]=sha(f)
p['aa_cases']=[f'aa{i:02d}' for i in range(1,5)];p['cases']=[dict(id=n,backend='original',group='aa') for n in p['aa_cases']];p['pairs']=[]
for i in range(1,5):
 pair=dict(original=f'pair{i:02d}_original',isolated=f'pair{i:02d}_isolated');p['pairs'].append(pair)
 for backend in (('original','isolated') if i%2 else ('isolated','original')):p['cases'].append(dict(id=pair[backend],backend=backend,group='ab',pair=i))
source=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz';assert sha(source)==p['input_sha256']['raw_frames.npz']
with np.load(source) as z:
 first=int(np.searchsorted(z['sample_indices'],p['checked_sample']-3500));origin=int(z['received_ns'][first])
 p['context_checkpoints']=[dict(sample=n,phase=phase,offset_ns=int(z['received_ns'][int(np.searchsorted(z['sample_indices'],n))])-origin) for n,phase in ((59904,'dense_start'),(65904,'mixed_start'))]
p['budget']='Exactly four same-backend A/A windows followed by fourAB pairs (AB,BA,AB,BA),12 unique fresh processes. Abort infrastructure/semantic/context failure; never restart/replace/extend to obtain severe baselines.'
p['qualification']='Every full raw/report/state, originalGUI/model/SDK work, role/sourceclock and final cleanup checks; commonGUI function bytes. Legacy four-pair symptomdecision unchanged. No exclusiveGIL or zero-observer qualification.'
p['limits']=['A/A estimates natural variance only; old3%/1% observer calibration failures remain.','SDK native hardware simulated; nohuman/USB/Run/formal edits.','Source/renderer/model/SDK policies identical; dynamic actual work retained, no posthoc matching.','Whole process boundary includes IPC and native scheduling differences; noGIL-only percentage.']
p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1')}
with (HERE/'plan02.json').open('x') as f:json.dump(p,f,indent=2)
print('Frozen',len(p['cases']),'cases;',len(p['sources']),'sources;',len(p['existing_sources']),'dependencies')
