"""Deploy a new exclusive Windows root and inert desktop entries; never launches capture."""
import hashlib,importlib.util,json,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('transport',ROOT/'experiments/ground_throughput_diagnosis/windows.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
ssh,transfer,HOST=w.ssh,w.transfer,w.HOST
REMOTE='E:/OptoJump/IronJump-single-usb-human-etw-20261017';REL='experiments/single_usb_human_etw'
PRIOR='E:/OptoJump/IronJump-single-usb-field-20261016'

def dependencies():
    command=f"$prior='{PRIOR}';$map=@{{}};$files=@(Get-ChildItem ($prior+'/camera/bin') -Recurse -File)+@(Get-ChildItem ($prior+'/models') -Recurse -File)+@(Get-Item ($prior+'/drivers/CyUsbInterface.dll'));foreach($file in $files){{$name=$file.FullName.Substring($prior.Length+1).Replace('\\','/');$map[$name]=(Get-FileHash $file.FullName).Hash.ToLower()}};@{{files=$map;source_root=$prior}}|ConvertTo-Json -Depth 4"
    value=json.loads(ssh(command,timeout=90))
    (HERE/'dependencies.json').write_text(json.dumps(value,indent=2)+'\n')

def freeze():
    files=[HERE/n for n in ('field_runner.py','queue_probe.py','native_clock.py','protocol.py','human_runner.py','entry.py','controller.py','schedule.wprp','launch.ps1','plan.json','dependencies.json')]
    (HERE/'frozen_sources.json').write_text(json.dumps({'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}},indent=2)+'\n')

def deploy():
    base=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    paths=[ROOT/n for n in base]+[ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json']
    paths += [p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.ps1','.wprp','.json','.md')]
    with zipfile.ZipFile(HERE/'deployment.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,str(p.relative_to(ROOT)))
    ssh(f"if(Test-Path '{REMOTE}'){{throw 'Exclusive root exists; do not overwrite'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    transfer(HERE/'deployment.zip',f'{HOST}:{REMOTE}/deployment.zip')
    digest=hashlib.sha256((HERE/'deployment.zip').read_bytes()).hexdigest()
    print(ssh(f"if((Get-FileHash '{REMOTE}/deployment.zip').Hash.ToLower() -ne '{digest}'){{throw 'Package hash'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/deployment.zip' '{REMOTE}';if($LASTEXITCODE -ne 0){{throw 'Unzip'}};New-Item -ItemType Directory '{REMOTE}/drivers'|Out-Null;Copy-Item '{PRIOR}/drivers/CyUsbInterface.dll' '{REMOTE}/drivers/';Copy-Item '{PRIOR}/camera/bin' '{REMOTE}/camera/bin' -Recurse;Copy-Item '{PRIOR}/models' '{REMOTE}/models' -Recurse;Get-PSDrive E|Select-Object Free|ConvertTo-Json",timeout=90))
    # Names are ASCII for robust console startup; the instructions and GUI are Chinese.
    script=f"""$folder=Join-Path ([Environment]::GetFolderPath('Desktop')) 'IronJump-ETW-20261017';if(Test-Path $folder){{throw 'Desktop folder exists'}};New-Item -ItemType Directory $folder|Out-Null;$shell=New-Object -ComObject WScript.Shell;foreach($mode in @('walk','run')){{foreach($trace in @('off','on')){{$name=$mode.ToUpper()+'-ETW-'+$trace.ToUpper();$shortcut=$shell.CreateShortcut((Join-Path $folder ($name+'.lnk')));$shortcut.TargetPath='C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';$shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass -File \"{REMOTE}/{REL}/launch.ps1\" -Mode '+$mode+' -Trace '+$trace;$shortcut.WorkingDirectory='{REMOTE}';$shortcut.Save()}}}};Copy-Item '{REMOTE}/{REL}/README.md' (Join-Path $folder 'README.txt');Get-ChildItem $folder|Select-Object Name,Length|ConvertTo-Json"""
    print(ssh(script))
    (HERE/'deployment_record.json').write_text(json.dumps({'root':REMOTE,'desktop_folder':'C:/Users/86150/Desktop/IronJump-ETW-20261017','package_sha256':digest,'files_packaged':len(paths),'capture_started':False},indent=2)+'\n')
if __name__=='__main__':dependencies();freeze();deploy()
