"""Hash-verified isolated deployment and bounded native Windows desktop tasks."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import time
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HOST = '86150@100.116.17.121'
REMOTE = 'E:/OptoJump/IronJump-runtime-fusion-20261015'
OLD = 'E:/OptoJump/IronJump-mirror-validation-20261014-01'
REL = 'experiments/runtime_single_frame_fusion'


def ssh(command, timeout=40):
    script = "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding;" + command
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', HOST,
                             'powershell -NoProfile -EncodedCommand ' + encoded], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout.decode('utf-8-sig', errors='replace') + result.stderr.decode(errors='replace'))
    return result.stdout.decode('utf-8-sig').strip()


def transfer(source, destination):
    subprocess.run(['scp', '-o', 'BatchMode=yes', str(source), str(destination)], check=True, timeout=120)


def deploy():
    manifest = json.loads((HERE / 'baseline_manifest.json').read_text())
    paths = {ROOT / name for name in manifest['base_files']}
    paths.update(p for p in (ROOT / 'exports').rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(p for p in HERE.iterdir() if p.is_file() and p.suffix in {'.py', '.json', '.txt'})
    paths.update((HERE / 'generated').glob('*.py'))
    package = HERE / 'deployment.zip'
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (HERE / 'deployment_manifest.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, str(p.relative_to(ROOT)))
        z.write(HERE / 'deployment_manifest.json', REL + '/deployment_manifest.json')
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    ssh(f"if(Test-Path '{REMOTE}'){{throw 'Destination exists'}};New-Item -ItemType Directory -Path '{REMOTE}'|Out-Null")
    transfer(package, f'{HOST}:{REMOTE}/deployment.zip')
    print(ssh(f"if((Get-FileHash '{REMOTE}/deployment.zip').Hash.ToLower() -ne '{sha}'){{throw 'Archive mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/deployment.zip' '{REMOTE}';exit $LASTEXITCODE"), flush=True)
    # Retain the recorded media in the new isolated tree; source is read-only.
    for filename in ('camera.mjpg', 'camera.csv'):
        relative = 'exports/ground_boundary_latency_20261014/field_run_20261015_02/' + filename
        print(ssh(f"Copy-Item '{OLD}/{relative}' '{REMOTE}/{relative}';if((Get-FileHash '{OLD}/{relative}').Hash -ne (Get-FileHash '{REMOTE}/{relative}').Hash){{throw 'Media mismatch'}}"), flush=True)
    print('DEPLOYED', len(hashes), 'verified package entries', flush=True)


def task(name, arguments, platform='windows', minutes=3):
    assert all(c.isalnum() or c in '_-' for c in name)
    task_name = 'IronJump-fusion-' + name
    output = f'{REMOTE}/{REL}/{name}'
    script = HERE / (name + '.ps1')
    script.write_text(f"""$ErrorActionPreference='Continue'
Set-Location '{REMOTE}'
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='{platform}';$env:PYTHONUTF8='1'
& D:/conda/python.exe {arguments} *> '{output}.log'
exit $LASTEXITCODE
""", encoding='utf-8')
    transfer(script, f'{HOST}:{REMOTE}/{REL}/{script.name}')
    ssh(f"""if(Test-Path '{output}'){{throw 'Existing output'}}
if(Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue){{throw 'Existing task'}}
$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$a=New-ScheduledTaskAction -Execute 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -Argument '-NoProfile -NonInteractive -File "{REMOTE}/{REL}/{script.name}"' -WorkingDirectory '{REMOTE}'
$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes {minutes}) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName '{task_name}' -Principal $p -Action $a -Settings $s|Out-Null
Start-ScheduledTask -TaskName '{task_name}'
""")
    print('START', name, flush=True)
    deadline = time.monotonic() + minutes * 60 + 30
    while True:
        time.sleep(3)
        state = json.loads(ssh(f"@{{state=[string](Get-ScheduledTask -TaskName '{task_name}').State;result=(Get-ScheduledTaskInfo -TaskName '{task_name}').LastTaskResult}}|ConvertTo-Json -Compress"))
        if state['state'] != 'Running':
            break
        if time.monotonic() > deadline:
            raise TimeoutError(name)
    transfer(f'{HOST}:{output}.log', HERE / (name + '.log'))
    ssh(f"Unregister-ScheduledTask -TaskName '{task_name}' -Confirm:$false")
    if state['result']:
        print((HERE / (name + '.log')).read_text(encoding='utf-16', errors='replace')[-4000:], flush=True)
        raise RuntimeError((name, state))
    print('DONE', name, flush=True)


def fetch(name):
    output = f'{REMOTE}/{REL}/{name}'
    ssh(f"& D:/conda/python.exe -m zipfile -c '{output}.zip' '{output}';exit $LASTEXITCODE")
    transfer(f'{HOST}:{output}.zip', HERE / (name + '.zip'))
    with zipfile.ZipFile(HERE / (name + '.zip')) as z:
        z.extractall(HERE)


def replay(name, variant):
    task(name, f"'{REMOTE}/{REL}/gui_probe.py' --variant {variant} --source offline --input '{REMOTE}/exports/ground_boundary_latency_20261014/field_run_20261015_02' --mode run --paint gui_final_v2 --cache-file '{REMOTE}/{REL}/fixed_geometry_cache.py' --cadence recorded --camera-replay --output '{REMOTE}/{REL}/{name}'")
    fetch(name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('deploy', 'checks', 'aa', 'trials'))
    args = parser.parse_args()
    if args.action == 'deploy':
        deploy()
    elif args.action == 'checks':
        task('windows_equivalence', f"'{REMOTE}/{REL}/check_equivalence.py'", platform='offscreen', minutes=10)
        transfer(f'{HOST}:{REMOTE}/{REL}/equivalence.json', HERE / 'windows_equivalence.json')
        for variant in 'ABC':
            task('tests_' + variant, f"'{REMOTE}/{REL}/run_tests.py' {variant}", platform='offscreen', minutes=5)
    elif args.action == 'aa':
        for name in ('aa_01_A', 'aa_02_A'):
            replay(name, 'A')
    else:
        assert (HERE / 'aa_verified.json').exists(), 'Verify A/A before formal trials'
        plan = json.loads((HERE / 'trial_plan.json').read_text())
        for block, sequence in enumerate(plan['blocks'], 1):
            for order, variant in enumerate(sequence, 1):
                replay(f'trial_{block:02d}_{order}_{variant}', variant)
