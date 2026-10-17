"""Fetch matching system PDBs and official Qt symbol archive to isolated cache."""
import hashlib
import json
import ntpath
from pathlib import Path
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
CACHE = HERE / 'symbol_cache01'
QT_ROOT = 'https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6111/qt6_6111_msvc2022_64/qt.qt6.6111.debug_info.win64_msvc2022_64/'
QT_FILE = '6.11.1-0-202605090529qtbase-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64-debug-symbols.7z'


def fetch(url, path):
    assert not path.exists()
    try:
        with urllib.request.urlopen(url,timeout=30) as response, path.open('xb') as stream:
            while chunk := response.read(1024*1024):
                stream.write(chunk)
        return {'url':url,'path':str(path.relative_to(HERE)),'status':200,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    except urllib.error.HTTPError as error:
        return {'url':url,'status':error.code}


def main():
    CACHE.mkdir(exist_ok=False)
    inventory = json.loads((HERE/'inventory01.json').read_text())
    records = []
    for image in inventory['images']:
        if ntpath.basename(image['path']).lower() not in {'ntdll.dll','kernelbase.dll','kernel32.dll','ucrtbase.dll'}:
            continue
        cv = image['codeview'][0]
        name = ntpath.basename(cv['pdb_path'])
        url = 'https://msdl.microsoft.com/download/symbols/'+name+'/'+cv['symbol_key']+'/'+name
        record = fetch(url,CACHE/name)
        records.append(record);print(record,flush=True)
    record = fetch(QT_ROOT+QT_FILE+'.sha1',CACHE/(QT_FILE+'.sha1'))
    records.append(record)
    record = fetch(QT_ROOT+QT_FILE,CACHE/QT_FILE)
    records.append(record);print(record,flush=True)
    expected = (CACHE/(QT_FILE+'.sha1')).read_text().strip().split()[0]
    assert hashlib.sha1((CACHE/QT_FILE).read_bytes()).hexdigest()==expected
    records[-1]['published_sha1_verified']=expected
    (HERE/'downloads01.json').write_text(json.dumps(records,indent=2)+'\n')


if __name__=='__main__':
    main()
