"""Read pixels only from the visible validation process window."""
import ctypes,sys
from PIL import ImageGrab
pid=int(sys.argv[1]);u=ctypes.windll.user32;handles=[]
cb=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
@cb
def enum(hwnd,_):
    p=ctypes.c_ulong();u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd),ctypes.byref(p))
    if p.value==pid and u.IsWindowVisible(ctypes.c_void_p(hwnd)):handles.append(hwnd)
    return True
u.EnumWindows(enum,0)
assert handles,'No visible validation window'
class Rect(ctypes.Structure):_fields_=[(n,ctypes.c_long) for n in ('left','top','right','bottom')]
rect=Rect();u.GetWindowRect(ctypes.c_void_p(handles[0]),ctypes.byref(rect))
assert rect.right>rect.left and rect.bottom>rect.top
ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom),all_screens=True).save(sys.argv[2])
print('Captured validation window:',pid,flush=True)
