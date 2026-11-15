"""Sequential run ledger; no scored performance processes overlap each other."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    pins = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}
    (HERE/'tooling_manifest.json').write_text(json.dumps({'files': pins, 'python': sys.version,
        'platform': platform.platform(), 'executable': sys.executable,
        'frozen_before_scored_runs': True}, indent=2))
    ledger = []
    for action in ('diagnostic', 'performance', 'pipeline', 'combined'):
        start=time.time()
        row={'action':action,'started_unix':start,'status':'running'}
        ledger.append(row)
        (HERE/'execution.json').write_text(json.dumps(ledger,indent=2))
        print('starting',action,flush=True)
        with (HERE/f'{action}.stdout').open('w') as out,(HERE/f'{action}.stderr').open('w') as err:
            r=subprocess.run([sys.executable,str(HERE/'run_suite.py'),action],cwd=ROOT,stdout=out,stderr=err)
        row.update(status='passed' if r.returncode==0 else 'failed',exit_code=r.returncode,
                   elapsed_s=time.time()-start)
        (HERE/'execution.json').write_text(json.dumps(ledger,indent=2))
        print(action,row['status'],round(row['elapsed_s'],2),flush=True)
        if r.returncode:return r.returncode
    if (HERE/'combined_features.json').exists():
        with (HERE/'regression_combined.stdout').open('w') as out,(HERE/'regression_combined.stderr').open('w') as err:
            r=subprocess.run([sys.executable,str(HERE/'regression.py'),'combined'],cwd=ROOT,stdout=out,stderr=err)
        ledger.append({'action':'regression_combined','status':'passed' if r.returncode==0 else 'failed',
                       'exit_code':r.returncode})
        (HERE/'execution.json').write_text(json.dumps(ledger,indent=2))
        if r.returncode:return r.returncode
    assert all(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==sha for name,sha in pins.items())
    print('all local phases complete; tooling pins unchanged',flush=True)
    return 0


if __name__=='__main__':
    sys.exit(main())
