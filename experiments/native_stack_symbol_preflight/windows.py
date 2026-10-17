"""Offline-only exclusive preparation root. Does not install or replace runtimes."""
import importlib.util
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('transport', ROOT / 'experiments/single_usb_human_etw/windows.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
REMOTE = 'E:/OptoJump/IronJump-native-symbol-preflight-20261017-01'
FIELD = 'E:/OptoJump/IronJump-single-usb-human-etw-20261017'
PRIOR = 'E:/OptoJump/IronJump-walk-etw-offline-20261017-01'
CASES = [('20261017_112623_8416401b_walk_on', 13992), ('20261017_113358_00ae9eca_walk_on', 12344)]


def main():
    from pe_identity import sha
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Exclusive root exists'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    files = ['inventory.py', 'pe_identity.py', 'ReadImages.cs']
    for name in files:
        w.transfer(HERE / name, f'{w.HOST}:{REMOTE}/{name}')
    (HERE / 'deployment01.json').write_text(json.dumps({'root': REMOTE, 'field_read_only': FIELD,
         'sources_sha256': {n: sha(HERE / n) for n in files}, 'new_capture_or_trace': False}, indent=2) + '\n')
    print(w.ssh(f'Set-Location "{REMOTE}";& "$env:windir/Microsoft.NET/Framework64/v4.0.30319/csc.exe" /nologo /unsafe /r:System.Web.Extensions.dll /out:ReadImages.exe ReadImages.cs;exit $LASTEXITCODE'), flush=True)
    print(w.ssh(f"Set-Location '{REMOTE}';$env:PYTHONUTF8='1';& D:/conda/python.exe inventory.py --field-root '{FIELD}' --output inventory01;exit $LASTEXITCODE", timeout=120), flush=True)
    for case, pid in CASES:
        # Decode the immutable copied original ETL, never start a session.
        etl = f'{FIELD}/experiments/single_usb_human_etw/runs/{case}/schedule.etl'
        print(w.ssh(f"& '{REMOTE}/ReadImages.exe' '{etl}' {pid} '{REMOTE}/{case}_images01.json';exit $LASTEXITCODE", timeout=120), flush=True)
    w.ssh(f"& D:/conda/python.exe -m zipfile -c '{REMOTE}/results01.zip' '{REMOTE}/inventory01' '{REMOTE}/{CASES[0][0]}_images01.json' '{REMOTE}/{CASES[1][0]}_images01.json';exit $LASTEXITCODE")
    w.transfer(f'{w.HOST}:{REMOTE}/results01.zip', HERE / 'results01.zip')
    target = HERE / 'results01'
    target.mkdir(exist_ok=False)
    with zipfile.ZipFile(HERE / 'results01.zip') as archive:
        archive.extractall(target)


if __name__ == '__main__':
    main()
