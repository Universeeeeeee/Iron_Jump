"""Archive both outcomes and immutable sources after the fixed pair terminates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    plan=read(HERE/'plan02.json');status=read(HERE/'runs/observation02/result01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['frozen_existing'].items())
    for name in status['cases']:assert not read(HERE/'runs/observation02'/name/'record01.json')['target_still_running']
    cmd="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    query=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,check=True)
    active=json.loads(query.stdout.decode('utf-8-sig')) if query.stdout.strip() else [];assert not active,'Processes still live; no archive finalization'
    names=set(plan['sources']);names.update(('plan01.json','plan02.json','preflight01.json','task01.stdout','task01.stderr','task02.stdout','task02.stderr'))
    names.update(p.relative_to(HERE).as_posix() for p in (HERE/'runs').rglob('*') if p.is_file())
    manifest={n:sha(HERE/n) for n in sorted(names) if (HERE/n).is_file()}
    old={n:sha(ROOT/n) for n in plan['frozen_existing'] if Path(n).suffix in ('.py','.json','.ps1','.sha256')}
    manifest.update({'old/'+n:v for n,v in old.items()})
    with (HERE/'manifest02.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence02.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(ROOT/n[4:] if n.startswith('old/') else HERE/n,n)
        z.write(HERE/'manifest02.json','manifest.json')
        for n in ('observation01','observation02'):z.write(HERE/'runs'/n/'active.lock',f'runs/{n}/active.lock/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence02.zip'),manifest_files=len(manifest),remaining_processes=active)))
