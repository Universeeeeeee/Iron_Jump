"""Verify actual stable-ABI error API targets in this own fresh process."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

if __name__ == '__main__':
    assert sys.platform == 'win32' and sys.version_info[:3] == (3, 11, 5)
    from PySide6 import QtWidgets
    path = Path('D:/conda/Lib/site-packages/shiboken6/shiboken6.abi3.dll')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == '47f4f9b44c95037565dd14f4be04f350f20c53c05483b750e0be867c39a7441e'
    k = C.WinDLL('kernel32', use_last_error=True)
    k.GetModuleHandleW.argtypes = [C.c_wchar_p]; k.GetModuleHandleW.restype = C.c_void_p
    base = k.GetModuleHandleW(str(path)); assert base
    targets = []
    for rva, name in [(0x337d0, 'PyErr_Occurred'), (0x33a80, 'PyErr_Restore')]:
        actual = C.c_void_p.from_address(base+rva).value
        expected = C.cast(getattr(C.pythonapi, name), C.c_void_p).value
        assert actual == expected
        targets.append(dict(iat_rva=rva, public_API=name, actual_target=actual, matches_CPython_export=True))
    result = dict(shiboken_sha256=digest, targets=targets,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='Own-process loaded IAT reads only. No error API invocation, Qt objects, QApplication, image, model, target attach, device or capture.')
    with Path(sys.argv[1]).open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
