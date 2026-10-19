"""Candidate setting only; original concurrent workload, no resize hashing or ETW."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    name=sys.argv[1];plan=json.loads((HERE/'plan01.json').read_text());assert name in plan['cases']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    import cv2
    binary=Path(cv2.__file__).parent/'cv2.pyd';assert sha(binary)==plan['cv2_sha256'];before=cv2.getNumThreads();assert before==plan['original_threads']
    setting=plan['opencv_variants'][name]
    if setting=='one':cv2.setNumThreads(1)
    after=cv2.getNumThreads();assert after==(1 if setting=='one' else before)
    spec=importlib.util.spec_from_file_location('original_concurrent_fixed_work',ROOT/'experiments/fixed_overlap_comparison/workload.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner);runner.HERE=HERE
    code=runner.child(name)
    meta=dict(setting=setting,before=before,after=after,at_end=cv2.getNumThreads(),binary_sha256=sha(binary),workload_returncode=code)
    with (HERE/'runs'/name/'cv2_config.json').open('x') as f:json.dump(meta,f,indent=2)
    raise SystemExit(code)
