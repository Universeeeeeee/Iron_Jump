"""Read public NumPy C entry pointers in a fresh, device-free Windows process."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import types

import numpy as np

EXPECTED = '4fb4c5d62a6bd766eea716350eaf5396580e33cf7dc159e305488d1b7d72dad2'
TARGETS = [0x17aea4, 0x172de9, 0x177434, 0x173161, 0xb909c,
           0x10041d, 0xfd80d, 0x107fe9, 0x103145,
           0x113cb0, 0x17ad66, 0x1002d2]


def main(output):
    assert sys.platform == 'win32' and sys.version_info[:2] == (3, 11)
    path = Path(np._core._multiarray_umath.__file__)
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [C.c_wchar_p]
    kernel.GetModuleHandleW.restype = C.c_void_p
    base = kernel.GetModuleHandleW(str(path))
    assert base
    header = struct.unpack_from('<I', data, 60)[0]
    assert data[header:header + 4] == b'PE\0\0'
    machine, count = struct.unpack_from('<HH', data, header + 4)
    optional_size = struct.unpack_from('<H', data, header + 20)[0]
    assert machine == 0x8664
    sections = {}
    for i in range(count):
        off = header + 24 + optional_size + i * 40
        name = data[off:off + 8].rstrip(b'\0').decode()
        sections[name] = struct.unpack_from('<IIII', data, off + 8)
    size, _, _, raw = sections['.pdata']
    ranges = [struct.unpack_from('<III', data, raw + i * 12)
              for i in range(size // 12)]

    def function_range(rva):
        found = [(a, b) for a, b, _ in ranges if a <= rva < b]
        assert len(found) <= 1
        return found[0] if found else None

    entries = []
    getfunc = C.pythonapi.PyCFunction_GetFunction
    getfunc.argtypes, getfunc.restype = [C.py_object], C.c_void_p

    def add(name, address):
        rva = address - base
        span = function_range(rva)
        size, start, _, _ = sections['.text']
        if start <= rva < start + size:
            entries.append(dict(public_entry=name, rva=rva,
                                unwind_range=list(span) if span else None))

    for label, obj in [('multiarray', np._core._multiarray_umath),
                       ('ndarray', np.empty(0)), ('ufunc', np.add)]:
        names = ([n for n, v in vars(np.ndarray).items()
                  if isinstance(v, types.MethodDescriptorType)]
                 if label == 'ndarray' else dir(obj))
        for name in names:
            value = getattr(obj, name)
            if isinstance(value, types.BuiltinFunctionType):
                add(label + '.' + name, getfunc(value))
    vectorcall = C.pythonapi.PyVectorcall_Function
    vectorcall.argtypes, vectorcall.restype = [C.py_object], C.c_void_p
    add('ufunc vectorcall (np.add)', vectorcall(np.add))
    getcapsule = C.pythonapi.PyCapsule_GetPointer
    getcapsule.argtypes, getcapsule.restype = [C.py_object, C.c_char_p], C.c_void_p
    includes = {}
    for api, capsule, filename in [('PyArray_API', '_ARRAY_API', '__multiarray_api.h'),
                                   ('PyUFunc_API', '_UFUNC_API', '__ufunc_api.h')]:
        header_path = Path(np.get_include()) / 'numpy' / filename
        includes[str(header_path)] = hashlib.sha256(header_path.read_bytes()).hexdigest()
        text = header_path.read_text().replace('\\\n', ' ')
        table = C.cast(getcapsule(getattr(np._core._multiarray_umath, capsule), None),
                       C.POINTER(C.c_void_p))
        for name, body in re.findall(r'^#define (\w+) ([^\n]+)', text, re.M):
            match = re.search(api + r'\[(\d+)\]', body)
            if match:
                address = table[int(match[1])]
                if address:
                    add(name, address)
    targets = []
    imports = {C.cast(getattr(C.pythonapi, name), C.c_void_p).value: name
               for name in ('PyEval_RestoreThread', 'PyEval_SaveThread')}
    for rva in TARGETS:
        span = function_range(rva)
        prefix = C.string_at(base + rva - 6, 6)
        call_name = None
        if prefix[:2] == b'\xff\x15':
            displacement = struct.unpack_from('<i', prefix, 2)[0]
            target = C.c_void_p.from_address(base + rva + displacement).value
            call_name = imports.get(target, 'other indirect target')
        targets.append(dict(rva=rva, unwind_range=list(span) if span else None,
            exact_public_entries=[e for e in entries if e['rva'] == rva],
            public_entries_in_same_unwind_range=[e for e in entries if e['unwind_range'] == list(span)] if span else [],
            preceding_32_bytes=C.string_at(base + rva - 32, 32).hex(),
            preceding_indirect_call=call_name))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED
    result = dict(python=sys.version, numpy=np.__version__, path=str(path), sha256=EXPECTED,
                  targets=targets, entries=entries, include_sha256=includes,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  scope='Public C entry pointers and PE unwind ranges only. No PDB/internal function names, live attachment, device access, timing benchmark or performance attribution.')
    with output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps(targets, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    main(parser.parse_args().output)
