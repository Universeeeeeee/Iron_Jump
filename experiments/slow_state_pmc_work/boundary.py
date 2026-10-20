"""Two native clock/OS-counter boundaries around each original compute phase."""
import ctypes as c
import hashlib
from pathlib import Path
class Marker(c.Structure):
    _fields_=[('tid',c.c_uint32),('reserved',c.c_uint32),('creation',c.c_uint64),('kernel',c.c_uint64),('user',c.c_uint64),('cycles',c.c_uint64),('qpc',c.c_int64)]
class Boundary:
    def __init__(self,plan):
        p=Path(__file__).with_name('boundary.dll')
        assert hashlib.sha256(p.read_bytes()).hexdigest()==plan['boundary_dll_sha256'] and c.sizeof(Marker)==48
        self.dll=c.CDLL(str(p))
        for name in ('boundary_begin','boundary_end'):
            f=getattr(self.dll,name);f.argtypes=[c.POINTER(Marker)];f.restype=c.c_uint32
    def mark(self,kind):
        assert kind in ('begin','end');m=Marker();assert getattr(self.dll,'boundary_'+kind)(c.byref(m))==0
        return {n:getattr(m,n) for n,_ in Marker._fields_}
