"""Own-process exactPE/C-API identity read; no image operation or allocation test."""
import ctypes as C
import hashlib
import importlib
import json
from pathlib import Path
import re
import struct
import sys
EXPECTED_CV='ae833b9b5771f5932200bd3b8ad0f483f4fbec92cbdbd26d21d38fe524c60e66'
EXPECTED_NP='4fb4c5d62a6bd766eea716350eaf5396580e33cf7dc159e305488d1b7d72dad2'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    assert sys.platform=='win32' and C.sizeof(C.c_void_p)==8 and sys.version_info[:2]==(3,11)
    import cv2
    import numpy as np
    cv=Path(cv2.__file__).parent/'cv2.pyd';multi=importlib.import_module('numpy._core._multiarray_umath');npy=Path(multi.__file__)
    assert sha(cv)==EXPECTED_CV and sha(npy)==EXPECTED_NP
    k=C.WinDLL('kernel32',use_last_error=True);k.GetModuleHandleW.argtypes=[C.c_wchar_p];k.GetModuleHandleW.restype=C.c_void_p
    base=k.GetModuleHandleW(str(cv));nb=k.GetModuleHandleW(str(npy));assert base and nb
    # Exact instructions independently decoded from this exact PE:
    # mov rcx,[rip+disp32] -> table; mov rax,[rcx+0x2e8];
    # mov rcx,[rcx+0x10]; call rax.
    first=C.string_at(base+0x1ea276e,7);assert first[:3]==bytes.fromhex('488b0d')
    pointer_rva=0x1ea276e+7+struct.unpack_from('<i',first,3)[0];assert pointer_rva==0x68ed630
    assert C.string_at(base+0x1ea2775,7)==bytes.fromhex('488b81e8020000')
    assert C.string_at(base+0x1ea27a3,4)==bytes.fromhex('488b4910') and C.string_at(base+0x1ea27a7,2)==bytes.fromhex('ffd0')
    table=C.c_void_p.from_address(base+pointer_rva).value;assert table
    getname=C.pythonapi.PyCapsule_GetName;getname.argtypes=[C.py_object];getname.restype=C.c_char_p
    getptr=C.pythonapi.PyCapsule_GetPointer;getptr.argtypes=[C.py_object,C.c_char_p];getptr.restype=C.c_void_p
    capsule=multi._ARRAY_API;array_api=getptr(capsule,getname(capsule));assert table==array_api
    at=lambda index:C.c_void_p.from_address(table+8*index).value
    assert at(2)==id(np.ndarray)
    header=Path(np.get_include())/'numpy/__multiarray_api.h';text=header.read_text(encoding='utf-8')
    match=re.search(r'#define PyArray_New\s*\\\n.*?PyArray_API\[(\d+)\]\)',text,re.S);assert match and int(match.group(1))==93
    constructor=at(93);assert nb<=constructor<nb+len(npy.read_bytes())+0x100000
    imports={}
    for return_rva,name in ((0x1ea260d,'PyGILState_Ensure'),(0x1ea2813,'PyGILState_Release')):
        code=C.string_at(base+return_rva-6,6);assert code[:2]==b'\xff\x15';iat=return_rva+struct.unpack_from('<i',code,2)[0]
        target=C.c_void_p.from_address(base+iat).value;expected=C.cast(getattr(C.pythonapi,name),C.c_void_p).value;assert target==expected
        imports[name]=dict(return_rva=return_rva,iat_rva=iat,target=target)
    result=dict(cv2_sha256=EXPECTED_CV,numpy_pyd_sha256=EXPECTED_NP,numpy_version=np.__version__,pointer_rva=pointer_rva,table_equals_numpy_array_api=True,
        pyarray_type_slot=2,type_slot_equals_numpy_ndarray=True,constructor_slot=93,constructor_public_api='PyArray_New',constructor_numpy_rva=constructor-nb,
        constructor_header_sha256=sha(header),constructor_header_excerpt=match.group(0),GIL_import_targets=imports,
        private_cpp_function_name=None,scope='Fresh process own module/C-API table reads only. No cv2 image function, model, GUI, SDK, USB, tracing orCPU load.',new_capture=False,script_sha256=sha(Path(__file__)))
    with Path(sys.argv[1]).open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('constructor_header_excerpt','GIL_import_targets')},indent=2))
