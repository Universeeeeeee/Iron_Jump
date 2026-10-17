"""New offline Windows root; no UI, device, SDK or trace entry point."""
import importlib.util
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('transport', ROOT / 'experiments/single_usb_human_etw/windows.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
REMOTE = 'E:/OptoJump/IronJump-walk-compute-offline-20261017-01'
INPUT = 'E:/OptoJump/IronJump-single-usb-human-etw-20261017/experiments/single_usb_human_etw/runs'
REL = 'experiments/walk_compute_offline_diagnosis'


def main():
    from replay import file_sha, read
    baseline = read(ROOT / 'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    paths = [ROOT / name for name in baseline] + [ROOT / 'experiments/runtime_single_frame_fusion/baseline_manifest.json', HERE / 'replay.py']
    package = HERE / 'deployment01.zip'
    assert not package.exists()
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT))
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Exclusive root exists'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    w.transfer(package, f'{w.HOST}:{REMOTE}/deployment.zip')
    sha = file_sha(package)
    print(w.ssh(f"if((Get-FileHash '{REMOTE}/deployment.zip').Hash.ToLower() -ne '{sha}'){{throw 'Hash'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/deployment.zip' '{REMOTE}';exit $LASTEXITCODE"), flush=True)
    (HERE / 'deployment01.json').write_text(json.dumps({'root': REMOTE, 'input_read_only': INPUT, 'package_sha256': sha,
                            'entry': f'{REL}/replay.py', 'GUI_USB_SDK_ETW_started': False}, indent=2) + '\n')
    print(w.ssh(f"Set-Location '{REMOTE}';$env:QT_API='pyside6';$env:PYTHONUTF8='1';& D:/conda/python.exe '{REL}/replay.py' --input '{INPUT}' --output '{REL}/windows01' --repeats 3;exit $LASTEXITCODE", timeout=600), flush=True)
    w.ssh(f"& D:/conda/python.exe -m zipfile -c '{REMOTE}/results01.zip' '{REMOTE}/{REL}/windows01';exit $LASTEXITCODE")
    w.transfer(f'{w.HOST}:{REMOTE}/results01.zip', HERE / 'windows_results01.zip')
    with zipfile.ZipFile(HERE / 'windows_results01.zip') as archive:
        assert not (HERE / 'windows01').exists()
        archive.extractall(HERE)


if __name__ == '__main__':
    main()
