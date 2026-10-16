"""Own Windows root/tasks, no periodic task-status subprocess during a trial."""
import importlib.util,json,sys,zipfile,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('old_windows',ROOT/'experiments/ground_throughput_diagnosis/windows.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
HOST=w.HOST;REMOTE='E:/OptoJump/IronJump-ground-backlog-measurement-20261016';REL='experiments/ground_backlog_measurement';PRIOR='E:/OptoJump/IronJump-beam-painter-state-20261015'
ssh,transfer=w.ssh,w.transfer

def sync():
    paths=[*HERE.glob('*.py'),HERE/'plan.json',HERE/'plan.sha256',HERE/'phases.json',*HERE.glob('*sources.json')]
    with zipfile.ZipFile(HERE/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in paths:archive.write(p,str(p.relative_to(ROOT)))
    transfer(HERE/'source.zip',f'{HOST}:{REMOTE}/source.zip')
    digest=hashlib.sha256((HERE/'source.zip').read_bytes()).hexdigest()
    print(ssh(f"if((Get-FileHash '{REMOTE}/source.zip').Hash.ToLower() -ne '{digest}'){{throw 'Hash mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source.zip' '{REMOTE}';exit $LASTEXITCODE"))

def launch(name,args,platform='windows'):
    name='IronJump-backlog-'+name;ps=HERE/(name+'.ps1');assert not ps.exists()
    ps.write_text(f"Set-Location '{REMOTE}'\n$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='{platform}';$env:PYTHONUTF8='1'\n& D:/conda/python.exe {args} *> '{REMOTE}/{REL}/{name}.log'\nexit $LASTEXITCODE\n")
    transfer(ps,f'{HOST}:{REMOTE}/{REL}/{ps.name}')
    print(ssh(f"if(Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue){{throw 'Existing task'}};$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited;$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -NonInteractive -File \"{REMOTE}/{REL}/{ps.name}\"' -WorkingDirectory '{REMOTE}';$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;Register-ScheduledTask -TaskName '{name}' -Principal $p -Action $a -Settings $s|Out-Null;Start-ScheduledTask -TaskName '{name}';'LAUNCHED {name}'"))

def fetch():
    code="from pathlib import Path;import zipfile;p=Path('"+REMOTE+'/'+REL+"');z=zipfile.ZipFile(p/'metadata.zip','w',zipfile.ZIP_DEFLATED);[(z.write(f,str(f.relative_to(p)))) for f in (p/'runs').rglob('*') if f.is_file() and f.suffix not in ('.mjpg','.png')];z.close()"
    # Pass an encoded script, avoiding shell interpolation of generated code.
    import base64
    encoded=base64.b64encode(code.encode()).decode()
    ssh("& D:/conda/python.exe -c \"import base64;exec(base64.b64decode('"+encoded+"'))\";exit $LASTEXITCODE")
    transfer(f'{HOST}:{REMOTE}/{REL}/metadata.zip',HERE/'metadata.zip')
    with zipfile.ZipFile(HERE/'metadata.zip') as archive:archive.extractall(HERE)

if __name__=='__main__':
    if sys.argv[1]=='deploy':
        base=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
        paths=[ROOT/x for x in base]+[ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json',ROOT/'experiments/ground_throughput_diagnosis/enabled_replay.py',ROOT/'experiments/beam_painter_state/baseline_renderer.py',ROOT/'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py']
        with zipfile.ZipFile(HERE/'base.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for p in paths:archive.write(p,str(p.relative_to(ROOT)))
        print(ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing root'}};Get-PSDrive E|Select-Object Free,Used|ConvertTo-Json -Compress;New-Item -ItemType Directory '{REMOTE}'|Out-Null"))
        transfer(HERE/'base.zip',f'{HOST}:{REMOTE}/base.zip')
        print(ssh(f"& D:/conda/python.exe -m zipfile -e '{REMOTE}/base.zip' '{REMOTE}';New-Item -ItemType Directory '{REMOTE}/{REL}' -Force|Out-Null;Copy-Item '{PRIOR}/experiments/beam_painter_state/inputs' '{REMOTE}/{REL}/inputs' -Recurse;Copy-Item '{PRIOR}/experiments/beam_painter_state/oracles' '{REMOTE}/{REL}/oracles' -Recurse",timeout=100))
        sync()
    else:sync()
