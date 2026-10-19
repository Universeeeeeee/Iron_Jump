"""Own-process public QLabel descriptor identity; instantiate no Qt objects."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import sys
import types


if __name__ == '__main__':
    assert sys.platform == 'win32' and C.sizeof(C.c_void_p) == 8
    assert sys.version_info[:3] == (3, 11, 5) and not hasattr(sys, 'gettotalrefcount')
    from PySide6 import QtWidgets
    path = Path(QtWidgets.__file__)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == '85cb6c2181b4b09887a7d8507dd950844d1b8f74a9c4002c7b71169f75bf6fda'
    descriptor = QtWidgets.QLabel.paintEvent
    assert type(descriptor) is types.MethodDescriptorType
    assert descriptor.__objclass__ is QtWidgets.QLabel and descriptor.__name__ == 'paintEvent'
    assert type(descriptor).__basicsize__ == 56
    header = Path('D:/conda/include/cpython/descrobject.h')
    source = header.read_text()
    assert 'PyDescr_COMMON;\n    PyMethodDef *d_method;\n    vectorcallfunc vectorcall;' in source
    # Exact non-debug CPython 3.11 x64 descriptor header, cross-checked with the
    # actual owning type/name objects before dereferencing the method definition.
    pointers = (C.c_void_p*7).from_address(id(descriptor))
    assert pointers[1] == id(type(descriptor))
    assert pointers[2] == id(descriptor.__objclass__) and pointers[3] == id(descriptor.__name__)
    method = pointers[5]
    assert C.c_char_p.from_address(method).value == b'paintEvent'
    function = C.c_void_p.from_address(method+8).value
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [C.c_wchar_p]
    kernel.GetModuleHandleW.restype = C.c_void_p
    base = kernel.GetModuleHandleW(str(path))
    assert base and function
    data = path.read_bytes(); pe = struct.unpack_from('<I', data, 60)[0]
    assert data[pe:pe+4] == b'PE\0\0' and struct.unpack_from('<H', data, pe+4)[0] == 0x8664
    count = struct.unpack_from('<H', data, pe+6)[0]
    optional = struct.unpack_from('<H', data, pe+20)[0]
    spans = []
    for i in range(count):
        at = pe+24+optional+40*i
        if data[at:at+8].rstrip(b'\0') == b'.pdata':
            size, _, _, raw = struct.unpack_from('<IIII', data, at+8)
            spans = [struct.unpack_from('<III', data, raw+12*j) for j in range(size//12)]
    rva = function-base
    ranges = [(a,b,u) for a,b,u in spans if a <= rva < b]
    assert len(ranges) == 1
    out = dict(public_entry='QLabel.paintEvent', entry_rva=rva, unwind_range=list(ranges[0]),
        retained_field_return_rva=0x1a8777, field_return_inside_entry=ranges[0][0] <= 0x1a8777 < ranges[0][1],
        module_sha256=digest, descriptor_header_sha256=hashlib.sha256(header.read_bytes()).hexdigest(),
        descriptor_basic_size=56, method_name_crosscheck=True, owner_type_crosscheck=True,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='Fresh process import and own descriptor/module reads only. No QApplication, Qt object, image, model, device, target attach or trace.',
        GIL_import_addresses={name:C.cast(getattr(C.pythonapi,name),C.c_void_p).value for name in
            ('PyEval_SaveThread','PyEval_RestoreThread','PyGILState_Ensure','PyGILState_Release')})
    with Path(sys.argv[1]).open('x') as f: json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
