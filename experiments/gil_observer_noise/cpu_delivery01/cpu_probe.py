"""Read coarse current CPU placement and SDK-typed OS metadata, never change policy."""
import ctypes as C
import os
import struct


def parse_sets(data,layout):
    if len(layout)!=6 or layout[0]<8:raise ValueError('Bad SDK layout')
    rows=[];pos=0
    while pos<len(data):
        if pos+8>len(data):raise ValueError('Truncated record header')
        size,kind=struct.unpack_from('<II',data,pos)
        if size<8 or pos+size>len(data):raise ValueError('Invalid record size')
        if kind==0:
            if size<layout[0] or any(off<8 or off+width>size for off,width in zip(layout[1:],(4,2,1,1,1))):raise ValueError('SDK field outside record')
            value=lambda i,fmt:struct.unpack_from(fmt,data,pos+layout[i])[0]
            rows.append(dict(id=value(1,'<I'),group=value(2,'<H'),logical=value(3,'<B'),core=value(4,'<B'),efficiency_class=value(5,'<B'),record_size=size,raw_hex=data[pos:pos+size].hex()))
        else:rows.append(dict(type=kind,record_size=size,raw_hex=data[pos:pos+size].hex()))
        pos+=size
    return rows


class CpuProbe:
    def __init__(self,path,clock):
        if os.name!='nt':raise OSError('Windows only')
        self.clock=clock;self.dll=C.PyDLL(str(path));self.dll.CurrentCpu.argtypes=[C.POINTER(C.c_uint32)];self.dll.CurrentCpu.restype=None
        self.dll.CpuSetLayout.argtypes=[C.POINTER(C.c_uint32)];self.dll.CpuSetLayout.restype=None
        self.dll.CpuSets.argtypes=[C.c_void_p,C.c_uint32,C.POINTER(C.c_uint32)];self.dll.CpuSets.restype=C.c_uint32
        self.dll.PowerState.argtypes=[C.POINTER(C.c_uint32)];self.dll.PowerState.restype=C.c_uint32
    def current(self):
        out=(C.c_uint32*2)();before=self.clock();self.dll.CurrentCpu(out);after=self.clock()
        return dict(host_before_ns=before,host_after_ns=after,group=out[0],logical=out[1])
    def topology(self):
        layout=(C.c_uint32*6)();self.dll.CpuSetLayout(layout);needed=C.c_uint32();error=self.dll.CpuSets(None,0,C.byref(needed))
        if error not in (0,122) or not 0<needed.value<=1048576:return dict(error=error,needed=needed.value,sdk_layout=list(layout),records=[])
        buf=C.create_string_buffer(needed.value);error=self.dll.CpuSets(buf,len(buf),C.byref(needed))
        if error:return dict(error=error,needed=needed.value,sdk_layout=list(layout),records=[])
        return dict(error=0,sdk_layout=list(layout),records=parse_sets(buf.raw[:needed.value],list(layout)))
    def power(self):
        out=(C.c_uint32*3)();error=self.dll.PowerState(out)
        return dict(error=error,version=out[0] if not error else None,control_mask=out[1] if not error else None,state_mask=out[2] if not error else None,scope='OS policy bits, not measured delivered frequency or a change request.')
