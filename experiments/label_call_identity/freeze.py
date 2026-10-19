import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((ROOT/'experiments/session_startup_accounting/plan01.json').read_text())
    for key in ('native_readiness','native_preparation_archive_sha256','state_labels','first_touch_sample','first_touch_offset_ns'):p.pop(key,None)
    p['cases']=[dict(id='identity01',backend='original',group='bounded_call_identity')]
    p['native_entry']=dict(entry_rva=0x1a8690,module_sha256='85cb6c2181b4b09887a7d8507dd950844d1b8f74a9c4002c7b71169f75bf6fda')
    p['budget']='Exactly one unchanged saved-source sharedGUI window. Record only the first three matching public QLabel paint calls with a non-null pixmap; detach immediately. No retries.'
    p['qualification']='Actual receiver/caller/parent identity, complete original raw/report/state and model/SDK closure. Identity observations are not native stacks or performance measurements.'
    p['limits']=['No GIL observer, trace, CPU ledger, candidate, live device ornewhuman run.','The GUI-thread sys.setprofile hook may perturb startup and dynamic frame selection; no latency/CPU comparison orold3%/1% upgrade.','New saved-workload receiver identity cannot recover an unrecorded historical field instance.']
    p['process_budget']=1;p['profile_call_budget']=3;p['performance_AB']=False
    p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1','.diff')}
    with (HERE/'plan02.json').open('x') as f:json.dump(p,f,indent=2)
    print('Frozen one original identity window; three before-native-call observations')
