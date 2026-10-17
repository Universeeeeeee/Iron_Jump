"""Read exact OpenCV public C entry ranges; execute no image operations."""
import argparse
import bisect
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import sys

import cv2

EXPECTED = 'ae833b9b5771f5932200bd3b8ad0f483f4fbec92cbdbd26d21d38fe524c60e66'
TARGETS = [0x1ae5f4c, 0x1ae5f56, 0x1b822a2, 0x1b822ac,
           0x1b9ceb2, 0x1b9cec0, 0x1ea260d, 0x1ea40af]


def main(output):
    assert sys.platform == 'win32' and sys.version_info[:2] == (3, 11)
    path = Path(cv2.__file__).parent / 'cv2.pyd'
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED
    k = C.WinDLL('kernel32', use_last_error=True)
    k.GetModuleHandleW.argtypes, k.GetModuleHandleW.restype = [C.c_wchar_p], C.c_void_p
    base = k.GetModuleHandleW(str(path))
    assert base
    pe = struct.unpack_from('<I', data, 60)[0]
    assert data[pe:pe + 4] == b'PE\0\0'
    machine, count = struct.unpack_from('<HH', data, pe + 4)
    optional = struct.unpack_from('<H', data, pe + 20)[0]
    assert machine == 0x8664
    sections = {}
    for i in range(count):
        off = pe + 24 + optional + i * 40
        sections[data[off:off + 8].rstrip(b'\0').decode()] = struct.unpack_from('<IIII', data, off + 8)
    size, _, _, raw = sections['.pdata']
    spans = [struct.unpack_from('<III', data, raw + i * 12) for i in range(size // 12)]
    starts = [a for a, b, unwind in spans]
    assert starts == sorted(set(starts))

    def span(rva):
        i = bisect.bisect_right(starts, rva) - 1
        return list(spans[i][:2]) if i >= 0 and rva < spans[i][1] else None

    getfunc = C.pythonapi.PyCFunction_GetFunction
    getfunc.argtypes, getfunc.restype = [C.py_object], C.c_void_p
    entries = []
    for name in ('resize', 'cvtColor', 'imdecode', 'flip'):
        rva = getfunc(getattr(cv2, name)) - base
        entries.append(dict(name='cv2.' + name, rva=rva, unwind_range=span(rva)))
    imports = {C.cast(getattr(C.pythonapi, name), C.c_void_p).value: name
               for name in ('PyEval_RestoreThread', 'PyEval_SaveThread', 'PyGILState_Ensure', 'PyGILState_Release')}
    targets = []
    for rva in TARGETS:
        prefix = C.string_at(base + rva - 6, 6)
        call = None
        if prefix[:2] == b'\xff\x15':
            displacement = struct.unpack_from('<i', prefix, 2)[0]
            address = C.c_void_p.from_address(base + rva + displacement).value
            call = imports.get(address, 'other indirect target')
        targets.append(dict(rva=rva, unwind_range=span(rva),
            matching_public_entries=[e['name'] for e in entries if e['unwind_range'] and e['unwind_range'] == span(rva)],
            preceding_32_bytes=C.string_at(base + rva - 32, 32).hex(),
            preceding_indirect_call=call))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED
    result = dict(path=str(path), sha256=EXPECTED, opencv_version=cv2.__version__,
        entries=entries, targets=targets, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='Fresh process, public PyCFunction pointers + exact PE .pdata and import-call checks only. No cv2 operation, GUI, camera, USB, process attachment or tracing. Internal functions remain module+RVA; no PDB match asserted.')
    with output.open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print(json.dumps(targets, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    main(parser.parse_args().output)
