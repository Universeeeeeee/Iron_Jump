"""Independent recomputation of retained controls; preserves original thresholds."""
import hashlib
import json
from pathlib import Path
from probe import delta

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((HERE/'plan01.json').read_text());r=json.loads((HERE/'result01.json').read_text());assert r['complete'] and not r['errors'] and r['sources_unchanged']
    assert all(sha(HERE/n)==h for n,h in p['sources'].items());assert list(r['cases'])==p['cases']
    cases={}
    for n,c in r['cases'].items():
        assert not c['worker_alive'] and all(c['checks'].values()) and 'error' not in c
        d=delta(c['before'],c['after'],p['read_bracket_ns_max']);assert d==c['delta']
        assert d['thread']['cpu_ms']<=d['wall_ms_bounds'][1]+32
        if 'worker_delta' in c:
            w=delta(c['worker_before'],c['worker_after'],p['read_bracket_ns_max']);assert w==c['worker_delta']
            assert w['thread']['cpu_ms']<=w['wall_ms_bounds'][1]+32
        cases[n]=dict(wall_ms_bounds=d['wall_ms_bounds'],thread_cpu_ms=d['thread']['cpu_ms'],process_cpu_ms=d['process']['cpu_ms'],thread_cycles=d['thread']['cycles'],worker_thread_cpu_ms=c.get('worker_delta',{}).get('thread',{}).get('cpu_ms'))
    with (HERE/'review01.json').open('x') as f:json.dump(dict(cases=cases,source_sha256=sha(Path(__file__)),plan_sha256=sha(HERE/'plan01.json'),result_sha256=sha(HERE/'result01.json'),boundary_read_ns_min=min(r['read_bracket_ns']),boundary_read_ns_max=max(r['read_bracket_ns']),synthetic_controls_pass=True,per_inference_precision_pass=False,actual_load_disturbance_pass=False,primary_root_identified=False),f,indent=2)
