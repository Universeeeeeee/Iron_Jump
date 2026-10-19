"""Stream only completed-case records; no mid-window target queries or retries."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

from gate import require_gate
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    require_gate(HERE)
    remote='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/model_process_isolation/performance'
    script=f"$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding;$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';$env:PYTHONUTF8='1';& D:/conda/python.exe -u '{remote}/cohort.py' 2>&1 | Tee-Object -FilePath '{remote}/cohort.stdout';exit $LASTEXITCODE"
    encoded=base64.b64encode(script.encode('utf-16le')).decode();lines=[]
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ControlPath=/tmp/ironjump-throughput-ssh','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','86150@100.116.17.121','powershell -NoProfile -EncodedCommand '+encoded]
    with (HERE/'launch_binding01.json').open('x') as f:json.dump(dict(script=script,plan_sha256=hashlib.sha256((HERE/'plan01.json').read_bytes()).hexdigest(),launcher_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),f,indent=2)
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    for line in proc.stdout:
        value=line.decode('utf-8-sig',errors='replace').rstrip();lines.append(value);print(value,flush=True)
    code=proc.wait()
    with (HERE/'execution01.json').open('x') as f:json.dump(dict(returncode=code,output=lines),f,indent=2)
    raise SystemExit(code)
