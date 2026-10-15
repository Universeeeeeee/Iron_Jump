"""Deliver and exercise an isolated, hash-verified tree. Original entry points stay untouched."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
HOST='86150@100.116.17.121'
REMOTE='E:/OptoJump/IronJump-mirror-validation-20261014-01'
REL='exports/ground_boundary_latency_20261014'

def ssh(ps,timeout=40):
    text="$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding;"+ps
    enc=base64.b64encode(text.encode('utf-16le')).decode()
    return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',HOST,'powershell -NoProfile -EncodedCommand '+enc],capture_output=True,timeout=timeout)

def logged(name,ps,timeout=40):
    p=ssh(ps,timeout)
    (HERE/(name+'.stdout')).write_bytes(p.stdout);(HERE/(name+'.stderr')).write_bytes(p.stderr)
    print(name,p.returncode,p.stdout.decode('utf-8-sig'),p.stderr.decode(errors='replace'),flush=True)
    if p.returncode:raise RuntimeError(name+' failed')
    return p

if __name__=='__main__':
    action=sys.argv[1]
    if action=='install':
        logged('isolation_create',"if(Test-Path '"+REMOTE+"'){throw 'Version exists'};New-Item -ItemType Directory -Path '"+REMOTE+"'|Out-Null")
        subprocess.run(['scp','-o','BatchMode=yes',str(HERE/'validation.zip'),HOST+':'+REMOTE+'/validation.zip'],check=True,timeout=60)
        local_sha=hashlib.sha256((HERE/'validation.zip').read_bytes()).hexdigest()
        logged('archive_hash',"$h=(Get-FileHash '"+REMOTE+"/validation.zip' -Algorithm SHA256).Hash.ToLower();if($h -ne '"+local_sha+"'){throw 'Archive mismatch'};$h")
        logged('extract',"& 'D:/conda/python.exe' -m zipfile -e '"+REMOTE+"/validation.zip' '"+REMOTE+"';exit $LASTEXITCODE")
        logged('verify',"& 'D:/conda/python.exe' '"+REMOTE+'/'+REL+"/verify_package.py';exit $LASTEXITCODE")
        logged('rollback',"& 'D:/conda/python.exe' '"+REMOTE+'/'+REL+"/preserve_windows.py';exit $LASTEXITCODE")
    elif action=='offline':
        ps="Set-Location '"+REMOTE+"';$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';"
        ps+="& 'D:/conda/python.exe' -m pytest -q tests/test_ground_mirror_boundaries.py tests/test_ground_payload_mirror.py tests/test_walking_fragment_restoration.py > '"+REMOTE+'/'+REL+"/windows_tests.log' 2>&1;if($LASTEXITCODE -ne 0){Get-Content '"+REMOTE+'/'+REL+"/windows_tests.log';exit $LASTEXITCODE};"
        ps+="& 'D:/conda/python.exe' '"+REMOTE+"/exports/ground_mirror_fragments_20261014/replay.py' windows > '"+REMOTE+'/'+REL+"/windows_replay.log' 2>&1;exit $LASTEXITCODE"
        ps=ps.replace("$env:QT_QPA_PLATFORM='offscreen';","$env:QT_QPA_PLATFORM='offscreen';$env:PYTHONUTF8='1';$ErrorActionPreference='Continue';")
        logged('windows_offline',ps,240)
        for remote,local in [('exports/ground_mirror_fragments_20261014/windows_replay.json','windows_replay.json'),(REL+'/windows_tests.log','windows_tests.log'),(REL+'/windows_replay.log','windows_replay.log'),(REL+'/rollback_manifest.json','rollback_manifest.json')]:
            subprocess.run(['scp','-o','BatchMode=yes',HOST+':'+REMOTE+'/'+remote,str(HERE/local)],check=True,timeout=60)
    elif action=='latency':
        for profile in ('normal','mirror_fragment'):
            out=REMOTE+'/'+REL+'/windows_final_'+profile
            logged('timing_'+profile,"Set-Location '"+REMOTE+"';$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';& 'D:/conda/python.exe' '"+REMOTE+'/'+REL+"/timing_probe.py' --profile "+profile+" --output '"+out+"';exit $LASTEXITCODE",45)
            subprocess.run(['scp','-r','-o','BatchMode=yes',HOST+':'+out,str(HERE)],check=True,timeout=60)
