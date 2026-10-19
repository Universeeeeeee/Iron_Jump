"""Explicit common simulated hardware backend; original serve/runtime unchanged."""
from collections import Counter
import hashlib
import os
import json
from pathlib import Path
import sys
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
calls=Counter()

class Control:
    def __init__(self):self._dll=object();self._idx=0
    def init(self):calls['init']+=1;return True
    def close(self):calls['close']+=1
    def set_fov(self,*args):calls['set_fov']+=1;return 0
    def set_auto_focus(self,*args):calls['set_auto_focus']+=1;return 0
    def set_exposure_compensation(self,*args):calls['set_exposure_compensation']+=1;return 0
    def set_anti_flicker(self,*args):calls['set_anti_flicker']+=1;return 0
    def set_wdr(self,*args):calls['set_wdr']+=1;return 0
    def set_ai_mode(self,*args):calls['set_ai_mode']+=1;return 0
    def set_ai_off(self,*args):calls['set_ai_off']+=1;return 0

class SDK:
    @classmethod
    def attach(cls,*args):calls['attach']+=1;return cls()
    def set_speed(self,*args):calls['set_speed']+=1
    def disable_ai(self):calls['disable_ai']+=1

if __name__=='__main__':
    from clocks import native_anchor
    startup_anchor=native_anchor()
    sys.modules['camera.tinyse_camera']=SimpleNamespace(TinySeCameraControl=Control)
    sys.modules['camera.gimbal_control']=SimpleNamespace(GimbalSdk=SDK)
    from camera.control_service import serve
    code=None
    try:code=serve()
    finally:
        with Path(sys.argv[1]).open('x') as f:json.dump(dict(backend='simulated_native_SDK',pid=os.getpid(),parent_pid=os.getppid(),clock_anchors=[startup_anchor,native_anchor()],calls=dict(calls),serve_returncode=code,
            original_serve_source_sha256=hashlib.sha256((ROOT/'camera/control_service.py').read_bytes()).hexdigest(),no_native_device_opened=True),f,indent=2)
    raise SystemExit(code)
