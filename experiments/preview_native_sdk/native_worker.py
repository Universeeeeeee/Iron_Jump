"""Original SDK serve/runtime with passive result witnesses; no fake classes."""
from collections import Counter
from functools import wraps
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
for folder in (ROOT,ROOT/'experiments/session_gui_vision'):sys.path.insert(0,str(folder))


def wrap_method(cls,name,calls):
    original=getattr(cls,name)
    @wraps(original)
    def invoke(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        calls[name]+=1
        return result
    setattr(cls,name,invoke)
    return original


if __name__=='__main__':
    from clocks import native_anchor
    from camera.tinyse_camera import TinySeCameraControl
    from camera.gimbal_control import GimbalSdk
    from camera.control_service import serve
    calls=Counter();patches=[];anchors=[native_anchor()];code=None;error=None
    for cls,name in [(TinySeCameraControl,'init'),(TinySeCameraControl,'close'),(GimbalSdk,'disable_ai'),(GimbalSdk,'set_speed')]:
        patches.append((cls,name,wrap_method(cls,name,calls)))
    # The init witness runs after real SDK discovery; GetModuleHandle checks
    # actual loaded native modules rather than merely files present on disk.
    original_init=TinySeCameraControl.init;images=[]
    def init(control):
        result=original_init(control)
        if result:
            kernel=C.WinDLL('kernel32');kernel.GetModuleHandleW.argtypes=[C.c_wchar_p];kernel.GetModuleHandleW.restype=C.c_void_p
            for name in ('obsbot_c_api.dll','libdev.dll'):
                handle=kernel.GetModuleHandleW(name);assert handle
                path=C.create_unicode_buffer(32768)
                kernel.GetModuleFileNameW.argtypes=[C.c_void_p,C.c_wchar_p,C.c_uint32]
                assert kernel.GetModuleFileNameW(handle,path,len(path))
                file=Path(path.value)
                images.append(dict(name=name,path=str(file),sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
        return result
    TinySeCameraControl.init=init
    try:code=serve()
    except BaseException as exc:error=repr(exc);raise
    finally:
        for cls,name,original in reversed(patches):setattr(cls,name,original)
        with Path(sys.argv[1]).open('x') as f:json.dump(dict(backend='real_native_SDK',pid=os.getpid(),parent_pid=os.getppid(),
            clock_anchors=anchors+[native_anchor()],calls=dict(calls),serve_returncode=code,error=error,
            actual_loaded_modules=images,no_native_device_opened=False,
            original_serve_source_sha256=hashlib.sha256((ROOT/'camera/control_service.py').read_bytes()).hexdigest()),f,indent=2)
    raise SystemExit(code)
