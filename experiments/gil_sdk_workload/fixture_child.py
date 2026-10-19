"""Only used by tests: original diagnostic entry, fake hardware, no native SDK."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sdk_receipt_entry',HERE.parent/'gil_sdk_entry/entry.py');entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)

class Control:
    def __init__(self):self._dll=object();self._idx=0
    def init(self):return True
    def close(self):pass
class SDK:
    @classmethod
    def attach(cls,*args):return cls()
    def set_speed(self,*args):pass
    def disable_ai(self):pass

if __name__=='__main__':
    sys.modules['camera.tinyse_camera']=SimpleNamespace(TinySeCameraControl=Control)
    sys.modules['camera.gimbal_control']=SimpleNamespace(GimbalSdk=SDK)
    raise SystemExit(entry.run(sys.argv[1]))
