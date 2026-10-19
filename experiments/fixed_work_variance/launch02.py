"""Stream only controller case-completion messages; no mid-task Windows queries."""
import base64
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    remote='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/fixed_work_variance'
    script=f"$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding;& D:/conda/python.exe -u '{remote}/run.py' 2>&1 | Tee-Object -FilePath '{remote}/controller02.stdout';if($LASTEXITCODE){{throw 'Fixed cohort failed; preserve all'}}"
    encoded=base64.b64encode(script.encode('utf-16le')).decode()
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ControlPath=/tmp/ironjump-throughput-ssh','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','86150@100.116.17.121','powershell -NoProfile -EncodedCommand '+encoded]
    received=[];process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    for line in process.stdout:
        text=line.decode('utf-8-sig',errors='replace').rstrip();received.append(text);print(text,flush=True)
    code=process.wait()
    with (HERE/'execution02.json').open('x') as f:json.dump(dict(script=script,returncode=code,controller_output=received,no_mid_task_queries=True),f,indent=2)
    raise SystemExit(code)
