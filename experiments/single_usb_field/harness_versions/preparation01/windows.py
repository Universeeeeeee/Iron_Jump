"""Exclusive Windows root; reuse read-only ssh transport, not the old replay."""
import base64,hashlib,importlib.util,json,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('transport',ROOT/'experiments/ground_throughput_diagnosis/windows.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
ssh,transfer,HOST=w.ssh,w.transfer,w.HOST
REMOTE='E:/OptoJump/IronJump-single-usb-field-20261016';REL='experiments/single_usb_field';PRIOR='E:/OptoJump/IronJump-single-usb-empty-20261016'

def freeze():
    files=[*HERE.glob('*.py'),HERE/'plan.json']
    value={'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (HERE/'frozen_sources.json').write_text(json.dumps(value,indent=2)+'\n')
def sync():
    paths=[*HERE.glob('*.py'),HERE/'plan.json',HERE/'frozen_sources.json']
    with zipfile.ZipFile(HERE/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,str(p.relative_to(ROOT)))
    transfer(HERE/'source.zip',f'{HOST}:{REMOTE}/source.zip')
    digest=hashlib.sha256((HERE/'source.zip').read_bytes()).hexdigest()
    print(ssh(f"if((Get-FileHash '{REMOTE}/source.zip').Hash.ToLower() -ne '{digest}'){{throw 'source hash'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source.zip' '{REMOTE}';exit $LASTEXITCODE"))
def deploy():
    base=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    with zipfile.ZipFile(HERE/'base.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in [*base,'experiments/runtime_single_frame_fusion/baseline_manifest.json']:z.write(ROOT/name,name)
    print(ssh(f"if(Test-Path '{REMOTE}'){{throw 'Root exists'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null"))
    transfer(HERE/'base.zip',f'{HOST}:{REMOTE}/base.zip')
    print(ssh(f"& D:/conda/python.exe -m zipfile -e '{REMOTE}/base.zip' '{REMOTE}';New-Item -ItemType Directory '{REMOTE}/drivers'|Out-Null;Copy-Item '{PRIOR}/drivers/CyUsbInterface.dll' '{REMOTE}/drivers/';Copy-Item '{PRIOR}/camera/bin' '{REMOTE}/camera/bin' -Recurse;Copy-Item '{PRIOR}/models' '{REMOTE}/models' -Recurse;New-Item -ItemType Directory '{REMOTE}/{REL}' -Force|Out-Null",timeout=90))
    sync()
def launch(name,stage):
    task='IronJump-single-usb-field-'+name;p=HERE/(task+'.ps1');assert not p.exists()
    p.write_text(f"Set-Location '{REMOTE}'\n$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1';$env:DAYU_DLL='{REMOTE}/drivers/CyUsbInterface.dll'\n& D:/conda/python.exe '{REMOTE}/{REL}/batch.py' {stage} *> '{REMOTE}/{REL}/{task}.log'\nexit $LASTEXITCODE\n")
    transfer(p,f'{HOST}:{REMOTE}/{REL}/{p.name}')
    print(ssh(f"if(Get-ScheduledTask -TaskName '{task}' -ErrorAction SilentlyContinue){{throw 'task exists'}};$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited;$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -NonInteractive -File \"{REMOTE}/{REL}/{p.name}\"' -WorkingDirectory '{REMOTE}';$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;Register-ScheduledTask -TaskName '{task}' -Principal $p -Action $a -Settings $s|Out-Null;Start-ScheduledTask -TaskName '{task}';'LAUNCHED {task}'"))
def fetch():
    code="from pathlib import Path;import zipfile;p=Path('"+REMOTE+'/'+REL+"');z=zipfile.ZipFile(p/'evidence.zip','w',zipfile.ZIP_DEFLATED);[z.write(f,str(f.relative_to(p))) for f in p.rglob('*') if f.is_file() and f.suffix!='.mjpg' and ('runs' in f.relative_to(p).parts or f.suffix=='.log')];z.close()"
    b64=base64.b64encode(code.encode()).decode();ssh("& D:/conda/python.exe -c \"import base64;exec(base64.b64decode('"+b64+"'))\";exit $LASTEXITCODE")
    transfer(f'{HOST}:{REMOTE}/{REL}/evidence.zip',HERE/'evidence.zip')
    with zipfile.ZipFile(HERE/'evidence.zip') as z:
        for name in z.namelist():
            dest=HERE/name;data=z.read(name)
            if dest.exists():assert dest.read_bytes()==data,name
            else:dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
if __name__=='__main__':
    if sys.argv[1]=='deploy':deploy()
    else:sync()
