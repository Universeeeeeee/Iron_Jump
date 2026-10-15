"""Isolated, hash-checked Windows deployment and native desktop diagnosis."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HOST = '86150@100.116.17.121'
REMOTE = 'E:/OptoJump/IronJump-throughput-diagnosis-20261015'
PRIOR = 'E:/OptoJump/IronJump-runtime-fusion-20261015'
ARCHIVE = 'E:/OptoJump/IronJump-mirror-validation-20261014-01'
REL = 'experiments/ground_throughput_diagnosis'
OLD_REL = 'experiments/runtime_single_frame_fusion'
LOCAL_PRIOR = Path('/Users/vae/.codex/worktrees/runtime-single-frame-fusion/Iron_Jump')
SOURCES = {'run': 'field_run_20261015_02', 'walk': 'field_walk_full_02'}


def ssh(command, timeout=45):
    script = "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding;" + command
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                             '-o', 'ControlPath=/tmp/ironjump-throughput-ssh',
                             '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', HOST,
                             'powershell -NoProfile -EncodedCommand ' + encoded], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout.decode('utf-8-sig', errors='replace') + result.stderr.decode(errors='replace'))
    return result.stdout.decode('utf-8-sig').strip()


def transfer(source, destination):
    subprocess.run(['scp', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                    '-o', 'ControlPath=/tmp/ironjump-throughput-ssh',
                    '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                    str(source), str(destination)], check=True, timeout=120)


def deploy():
    import shutil
    baseline = json.loads((ROOT / OLD_REL / 'baseline_manifest.json').read_text())['base_files']
    paths = {ROOT / name for name in baseline}
    paths.update(ROOT / OLD_REL / name for name in ('baseline_manifest.json', 'fixed_replay.py', 'fixed_geometry_cache.py'))
    for name in SOURCES.values():
        rel = Path('exports/ground_boundary_latency_20261014') / name
        (ROOT / rel).mkdir(parents=True, exist_ok=True)
        for filename in ('raw_frames.npz', 'report.json', 'timing.json', 'camera_record_start.json'):
            shutil.copy2(LOCAL_PRIOR / rel / filename, ROOT / rel / filename)
            paths.add(ROOT / rel / filename)
    paths.update(p for p in HERE.iterdir() if p.suffix in ('.py', '.json', '.sha256'))
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    (HERE / 'deployment_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    package = HERE / 'deployment.zip'
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, str(p.relative_to(ROOT)))
        z.write(HERE / 'deployment_manifest.json', REL + '/deployment_manifest.json')
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    ssh(f"if(Test-Path '{REMOTE}'){{throw 'Destination exists'}};New-Item -ItemType Directory -Path '{REMOTE}'|Out-Null")
    transfer(package, f'{HOST}:{REMOTE}/deployment.zip')
    print(ssh(f"if((Get-FileHash '{REMOTE}/deployment.zip').Hash.ToLower() -ne '{sha}'){{throw 'Archive mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/deployment.zip' '{REMOTE}';exit $LASTEXITCODE"), flush=True)
    media = {}
    for mode, name in SOURCES.items():
        if mode == 'walk':
            continue  # Historical raw walk JPEGs were converted to the preserved AVI.
        for filename in ('camera.mjpg', 'camera.csv'):
            rel = f'exports/ground_boundary_latency_20261014/{name}/{filename}'
            source = PRIOR if mode == 'run' else ARCHIVE
            media[rel] = ssh(f"Copy-Item '{source}/{rel}' '{REMOTE}/{rel}';$a=(Get-FileHash '{source}/{rel}').Hash;$b=(Get-FileHash '{REMOTE}/{rel}').Hash;if($a -ne $b){{throw 'Media mismatch'}};$b.ToLower()")
    (HERE / 'media_manifest.json').write_text(json.dumps(media, indent=2) + '\n')
    print('DEPLOYED', len(manifest), 'source entries; run media hashes checked', flush=True)


def task(name, arguments, minutes=3, platform='windows'):
    assert all(c.isalnum() or c in '_-' for c in name)
    task_name = 'IronJump-diagnosis-' + name
    output = f'{REMOTE}/{REL}/{name}'
    script = HERE / (name + '.ps1')
    script.write_text(f"""$ErrorActionPreference='Continue'
Set-Location '{REMOTE}'
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='{platform}';$env:PYTHONUTF8='1'
& D:/conda/python.exe {arguments} *> '{output}.log'
exit $LASTEXITCODE
""", encoding='utf-8')
    transfer(script, f'{HOST}:{REMOTE}/{REL}/{script.name}')
    ssh(f"""if(Test-Path '{output}.log'){{throw 'Existing output log'}}
if(Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue){{throw 'Existing task'}}
$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$a=New-ScheduledTaskAction -Execute 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -Argument '-NoProfile -NonInteractive -File "{REMOTE}/{REL}/{script.name}"' -WorkingDirectory '{REMOTE}'
$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes {minutes}) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName '{task_name}' -Principal $p -Action $a -Settings $s|Out-Null
Start-ScheduledTask -TaskName '{task_name}'
""")
    print('START', name, flush=True)
    deadline = time.monotonic() + minutes * 60 + 20
    state = None
    try:
        while True:
            time.sleep(3)
            try:
                state = json.loads(ssh(f"@{{state=[string](Get-ScheduledTask -TaskName '{task_name}').State;result=(Get-ScheduledTaskInfo -TaskName '{task_name}').LastTaskResult}}|ConvertTo-Json -Compress"))
            except (RuntimeError, subprocess.TimeoutExpired):
                if time.monotonic() > deadline:
                    raise
                print('RETRY read-only task status', name, flush=True)
                continue
            if state['state'] != 'Running':
                break
            if time.monotonic() > deadline:
                raise TimeoutError(name)
        transfer(f'{HOST}:{output}.log', HERE / (name + '.log'))
    finally:
        if state and state['state'] != 'Running':
            ssh(f"Unregister-ScheduledTask -TaskName '{task_name}' -Confirm:$false")
    if state['result']:
        print((HERE / (name + '.log')).read_text(encoding='utf-16', errors='replace')[-6000:], flush=True)
        raise RuntimeError((name, state))
    print('DONE', name, flush=True)


def fetch(relative):
    source = f'{REMOTE}/{REL}/{relative}'
    name = relative.replace('/', '_')
    ssh(f"& D:/conda/python.exe -m zipfile -c '{REMOTE}/{REL}/{name}.zip' '{source}';exit $LASTEXITCODE")
    transfer(f'{HOST}:{REMOTE}/{REL}/{name}.zip', HERE / (name + '.zip'))
    destination = HERE / str(Path(relative).parent)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(HERE / (name + '.zip')) as z:
        z.extractall(destination)


def replay(name, mode, level, offset=0):
    output = f'{REMOTE}/{REL}/runs/{name}'
    task(name, f"'{REMOTE}/{REL}/probe.py' --level {level} --sample-offset {offset} --source offline --input '{REMOTE}/exports/ground_boundary_latency_20261014/{SOURCES[mode]}' --mode {mode} --paint gui_final_v2 --cache-file '{REMOTE}/{OLD_REL}/fixed_geometry_cache.py' --cadence recorded --camera-replay --output '{output}'")
    fetch('runs/' + name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('deploy', 'oracles', 'calibrate', 'sync', 'media'))
    args = parser.parse_args()
    if args.action == 'deploy':
        deploy()
    elif args.action == 'sync':
        paths = list(HERE.glob('*.py')) + [HERE / name for name in ('plan.json', 'plan.sha256', 'phases.json')]
        paths += [p for p in (HERE / 'preview_state_plan.json', HERE / 'preview_state_sources.json') if p.exists()]
        package = HERE / 'source_update.zip'
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in paths:
                z.write(path, path.name)
            profiler = HERE / 'tools/py-spy.exe'
            if profiler.exists():
                z.write(profiler, 'tools/py-spy.exe')
        transfer(package, f'{HOST}:{REMOTE}/{REL}/{package.name}')
        sha = hashlib.sha256(package.read_bytes()).hexdigest()
        print(ssh(f"if((Get-FileHash '{REMOTE}/{REL}/{package.name}').Hash.ToLower() -ne '{sha}'){{throw 'Source package mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/{REL}/{package.name}' '{REMOTE}/{REL}';exit $LASTEXITCODE"))
    elif args.action == 'media':
        task('walk_media', f"'{REMOTE}/{REL}/prepare_walk_media.py'", minutes=5, platform='offscreen')
        transfer(f'{HOST}:{REMOTE}/{REL}/walk_media.json', HERE / 'walk_media.json')
    elif args.action == 'oracles':
        for mode, source in SOURCES.items():
            task('oracle_v2_' + mode, f"'{REMOTE}/{REL}/oracle.py' --input '{REMOTE}/exports/ground_boundary_latency_20261014/{source}' --mode {mode} --output '{REMOTE}/{REL}/oracles/{mode}'", platform='offscreen')
            fetch('oracles/' + mode)
    else:
        plan = json.loads((HERE / 'plan.json').read_text())
        for block, (order, offset) in enumerate(zip(plan['calibration']['orders'], plan['calibration']['sample_offsets']), 1):
            for mode in ('run', 'walk'):
                for level in order:
                    name = f'aa_{mode}_{block:02d}_{level}'
                    if (HERE / 'runs' / name / 'diagnostic.json').exists():
                        print('RETAIN completed', name, flush=True)
                        continue
                    replay(name, mode, level, offset)
