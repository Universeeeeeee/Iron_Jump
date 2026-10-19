"""Reuse delivery-qualified original work with a distinct immutable performance plan."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text())
    assert all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==v for n,v in plan['dependency_sources'].items())
    sys.path.insert(0,str(HERE.parent))
    spec=importlib.util.spec_from_file_location('qualified_isolation_work',HERE.parent/'workload.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner);runner.HERE=HERE
    raise SystemExit(runner.child(sys.argv[1]))
