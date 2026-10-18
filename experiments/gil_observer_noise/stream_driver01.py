"""Forward completed-case progress without launching status-query processes during ROI."""
from pathlib import Path
import json
import subprocess
import sys

r=Path(__file__).resolve().parent;stage=r/'confirmation01'
with (stage/'controller.log').open('x',encoding='utf-8') as log:
    child=subprocess.Popen([sys.executable,str(r/'runner_phase01.py'),'--plan',str(r/'confirmation_plan01.json'),'--tool',str(r/'observer.exe'),'--output',str(stage/'run01')],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
    for line in child.stdout:
        log.write(line);log.flush();print(line,end='',flush=True)
    code=child.wait()
with (stage/'exit.json').open('x') as f:json.dump(dict(returncode=code),f)
raise SystemExit(code)
