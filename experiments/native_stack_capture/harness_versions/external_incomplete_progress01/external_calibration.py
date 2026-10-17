"""Calibrate final --targets mode against two independent synthetic processes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main(a):
    plan=json.loads((HERE/'external_plan.json').read_text())
    for name,digest in plan['source_sha256'].items():
        if sha(HERE/name)!=digest:raise ValueError('Frozen external source changed: '+name)
    a.output.mkdir(parents=True,exist_ok=False)
    children=[]
    fixture_root=a.output/'synthetic'
    fixture_root.mkdir()
    try:
        targets=[]
        for process in ['gui','sdk']:
            child=subprocess.Popen([sys.executable,str(HERE/'external_fixture.py'),process,
                str(fixture_root/process),str(fixture_root/'stop')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            children.append(child)
            targets+=json.loads(child.stdout.readline())['targets']
        targets_file=a.output/'targets.json'
        targets_file.write_text(json.dumps(targets,indent=2)+'\n')
        time.sleep(.3)  # Supply progress observations before the external counter window.
        subprocess.run([sys.executable,str(HERE/'record.py'),a.mode,str(a.output/'window'),
                        '--targets',str(targets_file),'--seconds',str(plan['capture_seconds'])],check=True)
    finally:
        (fixture_root/'stop').touch()
        for child in children:
            try:
                stdout,stderr=child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate();stdout,stderr=child.communicate(timeout=5)
            (a.output/('child_'+str(child.pid)+'.json')).write_text(json.dumps(dict(returncode=child.returncode,stdout=stdout,stderr=stderr),indent=2)+'\n')
            if child.returncode:raise RuntimeError('Synthetic child failed; preserve output')
    (a.output/'plan_reference.json').write_text(json.dumps(dict(external_plan_sha256=sha(HERE/'external_plan.json'),
        source_sha256=plan['source_sha256'],synthetic_only=True),indent=2)+'\n')
    if a.mode!='off':
        subprocess.run([sys.executable,str(HERE/'split_field.py'),str(a.output/'window'),str(a.output/'split')],check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['off','cpu','wait'])
    p.add_argument('output',type=Path)
    main(p.parse_args())
