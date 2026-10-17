"""Add one frozen offline-only script to the isolated diagnosis root."""
import json
from pathlib import Path
import zipfile
from windows import w, REMOTE, REL, INPUT
from replay import file_sha

HERE = Path(__file__).resolve().parent
assert not (HERE / 'chain_deployment01.json').exists()
sha = file_sha(HERE / 'chain.py')
w.transfer(HERE / 'chain.py', f'{w.HOST}:{REMOTE}/{REL}/chain.py')
(HERE / 'chain_deployment01.json').write_text(json.dumps({'script_sha256': sha, 'root': REMOTE, 'input_read_only': INPUT,
                                      'output': f'{REL}/windows_chain01', 'GUI_USB_SDK_ETW_started': False}, indent=2) + '\n')
print(w.ssh(f"if((Get-FileHash '{REMOTE}/{REL}/chain.py').Hash.ToLower() -ne '{sha}'){{throw 'Source hash'}};Set-Location '{REMOTE}';$env:QT_API='pyside6';$env:PYTHONUTF8='1';& D:/conda/python.exe '{REL}/chain.py' --input '{INPUT}' --output '{REL}/windows_chain01' --repeats 3;exit $LASTEXITCODE", timeout=600), flush=True)
w.ssh(f"& D:/conda/python.exe -m zipfile -c '{REMOTE}/chain01.zip' '{REMOTE}/{REL}/windows_chain01';exit $LASTEXITCODE")
w.transfer(f'{w.HOST}:{REMOTE}/chain01.zip', HERE / 'windows_chain01.zip')
with zipfile.ZipFile(HERE / 'windows_chain01.zip') as archive:
    assert not (HERE / 'windows_chain01').exists()
    archive.extractall(HERE)
assert file_sha(HERE / 'chain.py') == sha, 'Local source changed during run'
