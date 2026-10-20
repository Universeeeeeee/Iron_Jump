import subprocess,sys
from datetime import datetime
from pathlib import Path
HERE=Path(__file__).resolve().parent;folder=HERE/'runs'/('steady_walk_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
code=subprocess.run([sys.executable,str(HERE/'field_walk.py'),'--output',str(folder)]).returncode
if code==0:code=subprocess.run([sys.executable,str(HERE/'analyze_walk.py'),str(folder)]).returncode
print('证据目录:',folder);raise SystemExit(code)
