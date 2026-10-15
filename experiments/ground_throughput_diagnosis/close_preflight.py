"""Close only this experiment's unarmed, DLL-failed preparation window."""
import ctypes,json
from pathlib import Path
here=Path(__file__).resolve().parent
import sys
folder=here/'runs'/sys.argv[1]
assert not (folder/'armed.json').exists()
status=json.loads((folder/'camera_live.json').read_text(encoding='utf-8'))
assert not status['running']
target=json.loads((folder/'pid.json').read_text())['pid']
user=ctypes.windll.user32
callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
closed=[]
def visit(hwnd,_):
    pid=ctypes.c_ulong();user.GetWindowThreadProcessId(ctypes.c_void_p(hwnd),ctypes.byref(pid))
    if pid.value==target:
        title=ctypes.create_unicode_buffer(512);user.GetWindowTextW(ctypes.c_void_p(hwnd),title,512)
        if title.value.startswith('IronJump LIVE diagnosis'):
            assert user.PostMessageW(ctypes.c_void_p(hwnd),0x10,0,0)
            closed.append(title.value)
    return True
user.EnumWindows(callback(visit),0)
print(json.dumps({'target_pid':target,'closed':closed}),flush=True)
