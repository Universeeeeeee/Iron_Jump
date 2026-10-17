"""End-to-end external observer test with two synthetic timer processes, no GUI/SDK load."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent


def main(output):
    output.mkdir(exist_ok=False)
    children=[]
    try:
        for role in ['gui','sdk']:  # routing labels only: both are synthetic Python timer processes
            child=subprocess.Popen([sys.executable,str(Path(__file__)),'--child'],stdout=subprocess.PIPE,text=True)
            children.append(child)
        targets=[dict(json.loads(c.stdout.readline()),role=role) for c,role in zip(children,['gui','sdk'])]
        target_path=output/'synthetic_targets.json'
        target_path.write_text(json.dumps(targets,indent=2)+'\n')
        subprocess.run([sys.executable,str(HERE/'record.py'),'wait',str(output/'window'),'--targets',str(target_path)],check=True)
        subprocess.run([sys.executable,str(HERE/'split_field.py'),str(output/'window'),str(output/'split')],check=True)
        (output/'scope.json').write_text(json.dumps(dict(synthetic_only=True,real_GUI_started=False,real_SDK_started=False,
                                                       targets=targets),indent=2)+'\n')
    finally:
        for child in children:
            # Terminate only the synthetic children created here, after the observation window.
            child.terminate()
            child.wait(timeout=5)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('output',type=Path,nargs='?')
    p.add_argument('--child',action='store_true')
    a=p.parse_args()
    if a.child:
        print(json.dumps(dict(pid=os.getpid(),tid=ctypes.WinDLL('kernel32').GetCurrentThreadId())),flush=True)
        for _ in range(1600):time.sleep(0.025)
    else:main(a.output)
