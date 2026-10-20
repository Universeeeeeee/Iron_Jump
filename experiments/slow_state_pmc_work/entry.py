"""Same fixed work in two actual Windows sessions; no policy setter."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
if __name__=='__main__':
    name=sys.argv[1];plan=json.loads((HERE/'plan01.json').read_text());assert name in plan['cases']
    output=HERE/'runs'/(name+'.context.json')
    original=list(sys.argv)
    try:
        sys.argv=['read_context.py',str(output)]
        runpy.run_path(str(ROOT/'experiments/qos_context_review/read_context.py'),run_name='__main__')
    finally:sys.argv=original
    sys.path.insert(0,str(HERE));import workload
    code=workload.child(name)
    if code==0:
        from verify import check,identity
        result=json.loads((HERE/'runs'/name/'result.json').read_text())
        reference=json.loads((HERE/'reference01.json').read_text())
        assert check(plan,result)['pass_all'] and identity(result)==identity(reference)
    raise SystemExit(code)
