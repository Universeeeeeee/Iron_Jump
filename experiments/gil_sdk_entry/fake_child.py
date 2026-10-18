"""Fake hardware only. Real imported serve, runtime, mailbox and stdin pipe."""
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

from entry import run

folder=Path(sys.argv[1]);mode=sys.argv[2]
def mark(name):
    with (folder/name).open('x') as f:f.write(str(threading.get_native_id()))
def gate(name):
    mark(name+'_entered');deadline=time.monotonic()+5
    while not (folder/(name+'_release')).exists():
        if time.monotonic()>deadline:raise TimeoutError(name)
        time.sleep(.001)


class Input:
    def __init__(self,source):self.source=iter(source);self.previous=0
    def __iter__(self):return self
    def __next__(self):
        if self.previous:mark('processed_'+str(self.previous))
        value=next(self.source);self.previous+=1;return value


class Control:
    def __init__(self):self._dll=object();self._idx=0
    def init(self):return True
    def set_fov(self,*args):gate('setting');return 0
    def close(self):mark('hardware_closed')


class SDK:
    @classmethod
    def attach(cls,*args):
        if mode=='constructor_gap':gate('attach')
        return cls()
    def set_speed(self,*args):return 0
    def disable_ai(self):return 0


if __name__=='__main__':
    sys.modules['camera.tinyse_camera']=SimpleNamespace(TinySeCameraControl=Control)
    sys.modules['camera.gimbal_control']=SimpleNamespace(GimbalSdk=SDK)
    sys.stdin=Input(sys.stdin)
    raise SystemExit(run(folder/'child'))
