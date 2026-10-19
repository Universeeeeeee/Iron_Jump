"""Archive the new protocol case, preserving both original and tail snapshots."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    plan=read(HERE/'plan01.json');r=read(HERE/'runs/protocol01/record01.json');assert not r['target_still_running']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    cmd="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,check=True);active=json.loads(p.stdout.decode('utf-8-sig')) if p.stdout.strip() else [];assert not active
    names=set(plan['sources']);names.update(('plan01.json','task01.stdout','task01.stderr','audit01.json','wpr_status01.txt','windows_tests01.stdout','windows_tests01.stderr'))
    names.update(p.relative_to(HERE).as_posix() for p in (HERE/'runs').rglob('*') if p.is_file())
    manifest={n:sha(HERE/n) for n in sorted(names) if (HERE/n).is_file()}
    previous={n:v for n,v in plan['existing_sources'].items() if Path(n).suffix in ('.py','.json','.ps1','.sha256')}
    manifest.update({'old/'+n:v for n,v in previous.items()})
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(ROOT/n[4:] if n.startswith('old/') else HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for lock in (HERE/'runs').rglob('active.lock'):z.write(lock,lock.relative_to(HERE).as_posix()+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),remaining_processes=active)))
