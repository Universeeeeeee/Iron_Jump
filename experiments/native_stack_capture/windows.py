"""Explicit deploy/run/fetch for synthetic calibration only."""
import argparse
import importlib.util
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('transport', ROOT / 'experiments/ground_throughput_diagnosis/windows.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
REMOTE = 'E:/OptoJump/IronJump-native-stack-capture-20261017-01'


def deploy():
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Exclusive directory exists'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    for p in HERE.iterdir():
        if p.suffix in ('.py', '.cs', '.wprp', '.ps1', '.json', '.md'):
            w.transfer(p, f'{w.HOST}:{REMOTE}/{p.name}')
    print(w.ssh(f"Set-Location '{REMOTE}'; & $env:windir/Microsoft.NET/Framework64/v4.0.30319/csc.exe /nologo /unsafe /r:System.Web.Extensions.dll /out:ReadStacks.exe ReadStacks.cs;exit $LASTEXITCODE"))


def run(name, mode):
    if not name.replace('_', '').isalnum():
        raise ValueError(name)
    print(w.ssh(f"Set-Location '{REMOTE}'; $env:PYTHONUTF8='1'; & D:/conda/python.exe record.py {mode} '{REMOTE}/runs/{name}';exit $LASTEXITCODE", timeout=90))
    if mode != 'off':
        print(w.ssh(f"$f=Get-Content '{REMOTE}/runs/{name}/fixture/fixture.json' -Raw|ConvertFrom-Json;$t=($f.threads.psobject.Properties|ForEach-Object {{$_.Value.before.tid}})-join ','; & '{REMOTE}/ReadStacks.exe' '{REMOTE}/runs/{name}/trace.etl' $f.pid $t '{REMOTE}/runs/{name}/decoded';exit $LASTEXITCODE", timeout=90))
    w.ssh(f"& D:/conda/python.exe -m zipfile -c '{REMOTE}/{name}.zip' '{REMOTE}/runs/{name}';exit $LASTEXITCODE")
    w.transfer(f'{w.HOST}:{REMOTE}/{name}.zip', HERE / f'{name}.zip')
    (HERE / 'runs').mkdir(exist_ok=True)
    with zipfile.ZipFile(HERE / f'{name}.zip') as z:
        z.extractall(HERE / 'runs')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['deploy', 'run'])
    p.add_argument('--name')
    p.add_argument('--mode', choices=['off', 'cpu', 'wait'])
    a = p.parse_args()
    if a.action == 'deploy': deploy()
    else: run(a.name, a.mode)
