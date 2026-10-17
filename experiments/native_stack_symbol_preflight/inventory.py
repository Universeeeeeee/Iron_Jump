"""No app/hardware entry point: version/module/PE and local-PDB inventory."""
import argparse
import ctypes
from ctypes import wintypes as w
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys

from pe_identity import pe, pdb, sha


def modules():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    handle = kernel.GetCurrentProcess()
    psapi.EnumProcessModules.argtypes = [w.HANDLE, ctypes.POINTER(w.HMODULE), w.DWORD, ctypes.POINTER(w.DWORD)]
    psapi.GetModuleFileNameExW.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]
    array = (w.HMODULE * 4096)()
    needed = w.DWORD()
    assert psapi.EnumProcessModules(handle, array, ctypes.sizeof(array), ctypes.byref(needed))
    assert needed.value <= ctypes.sizeof(array)
    result = []
    for handle_module in array[:needed.value // ctypes.sizeof(w.HMODULE)]:
        text = ctypes.create_unicode_buffer(32768)
        assert psapi.GetModuleFileNameExW(handle, handle_module, text, len(text))
        result.append(text.value)
    return result


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    # Import libraries only; no Q(Core)Application, windows, camera/USB/SDK object.
    import numpy as np
    from PySide6 import QtCore, QtGui, QtWidgets
    np.add(np.zeros(1), 1)  # Resolve normal core extension imports; not a benchmark.
    loaded = modules()
    root = Path(sys.prefix)
    field = args.field_root
    paths = {Path(p) for p in loaded}
    paths.update(p for folder in [field / 'camera/bin', field / 'drivers'] if folder.exists() for p in folder.glob('*.dll'))
    relevant = []
    prefixes = (str(root).lower(), str(field).lower())
    system_names = {'ntdll.dll', 'kernelbase.dll', 'kernel32.dll', 'ucrtbase.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll'}
    for path in sorted(paths):
        if str(path).lower().startswith(prefixes) or path.name.lower() in system_names:
            info = pe(path)
            info['loaded_in_library_smoke'] = str(path).lower() in {p.lower() for p in loaded}
            relevant.append(info)
    search_roots = [root, root / 'DLLs', root / 'Library/bin', root / 'Lib/site-packages/PySide6',
                    root / 'Lib/site-packages/shiboken6', root / 'Lib/site-packages/numpy', field / 'camera/bin', field / 'drivers']
    candidates = set()
    searches = []
    for folder in search_roots:
        # Bounded search: direct children except numpy subtree. No full-prefix crawl.
        files = list(folder.rglob('*.pdb') if folder.name == 'numpy' else folder.glob('*.pdb')) if folder.exists() else []
        candidates.update(files)
        searches.append({'root': str(folder), 'recursive': folder.name == 'numpy', 'matches': len(files)})
    records = []
    for file in candidates:
        try:
            records.append(pdb(file))
        except (AssertionError, ValueError) as error:
            records.append({'path': str(file), 'error': str(error)})
    metadata = []
    for file in (root / 'conda-meta').glob('python-3.11*.json'):
        meta = json.loads(file.read_text())
        metadata.append({k: meta.get(k) for k in ('name', 'version', 'build', 'channel', 'url', 'sha256')})
        metadata[-1]['pdb_files_in_package_manifest'] = [p for p in meta.get('files', []) if p.lower().endswith('.pdb')]
    value = {'scope': 'Offline library import smoke, not the original field process module list. Historical ETL must cross-check identities. No app, devices or trace started.',
             'platform': platform.platform(), 'python': sys.version, 'executable': sys.executable, 'prefix': sys.prefix,
             'versions': {'numpy': np.__version__, 'PySide6': importlib.metadata.version('PySide6'), 'shiboken6': importlib.metadata.version('shiboken6'), 'Qt': QtCore.qVersion()},
             'loaded_module_paths': loaded, 'images': relevant, 'pdb_searches': searches, 'local_pdbs': records,
             'conda_python_packages': metadata, 'scripts': {n: sha(Path(__file__).with_name(n)) for n in ['inventory.py', 'pe_identity.py']}}
    (args.output / 'inventory.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print('IMAGES', len(relevant), 'LOCAL_PDBS', len(records), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--field-root', type=Path, required=True)
    main(parser.parse_args())
