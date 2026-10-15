"""Close only the specifically identified validation GUI through normal WM_CLOSE."""
import ctypes
import sys
pid=int(sys.argv[1]);u=ctypes.windll.user32;found=[]
callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
@callback
def enum(hwnd,_):
    owner=ctypes.c_ulong();u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd),ctypes.byref(owner))
    if owner.value==pid and u.IsWindowVisible(ctypes.c_void_p(hwnd)):
        found.append(int(hwnd));u.PostMessageW(ctypes.c_void_p(hwnd),0x0010,0,0)
    return True
u.EnumWindows(enum,0)
print('Requested normal close:',pid,found,flush=True)
