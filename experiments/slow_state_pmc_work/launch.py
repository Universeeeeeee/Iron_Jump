"""Stream the frozen controller only; no mid-window remote monitoring processes."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    remote='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/slow_state_pmc_work'
    script=f"$ErrorActionPreference='Continue';[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding;$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';$env:PYTHONUTF8='1';Set-Location 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01';& D:/conda/python.exe -u '{remote}/capture.py';exit $LASTEXITCODE"
    encoded=base64.b64encode(script.encode('utf-16le')).decode()
    args=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ControlPath=/tmp/ironjump-throughput-ssh',
        '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','86150@100.116.17.121','powershell -NoProfile -EncodedCommand '+encoded]
    with (HERE/'launch_binding01.json').open('x') as f:json.dump(dict(plan_sha256=hashlib.sha256((HERE/'plan01.json').read_bytes()).hexdigest(),analyzer_sha256=hashlib.sha256((HERE/'analyze.py').read_bytes()).hexdigest(),cohort_sha256=hashlib.sha256((HERE/'cohort.ps1').read_bytes()).hexdigest(),script=script),f,indent=2)
    target=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    with (HERE/'controller_stream01.log').open('xb') as log:
        for line in target.stdout:
            log.write(line);log.flush();print(line.decode('utf-8-sig',errors='replace').rstrip(),flush=True)
    rc=target.wait()
    with (HERE/'transport_execution01.json').open('x') as f:json.dump(dict(ssh_returncode=rc,scope='SSH transport terminal state; inspect remote controller and child records separately.'),f,indent=2)
    raise SystemExit(rc)
