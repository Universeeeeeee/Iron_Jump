"""Three GUI-thread protected-call identities, not a timing/GIL profiler."""
import ctypes as C
import hashlib
from pathlib import Path
import sys
import time
import types


class Identity:
    def __init__(self,root,entry):
        from PySide6 import QtWidgets
        self.widgets=QtWidgets;self.root=Path(root);self.entry=entry;self.budget=3
        self.rows=[];self.errors=[];self.auto_detached=False;self.previous=None
        self.module=Path(QtWidgets.__file__)
        assert hashlib.sha256(self.module.read_bytes()).hexdigest()==entry['module_sha256']
        k=C.PyDLL('kernel32');k.GetModuleHandleW.argtypes=[C.c_wchar_p];k.GetModuleHandleW.restype=C.c_void_p
        k.GetCurrentThreadId.argtypes=[];k.GetCurrentThreadId.restype=C.c_uint32
        self.base=k.GetModuleHandleW(str(self.module));assert self.base
        self.tid=k.GetCurrentThreadId;self.gui_tid=self.tid()
        self.getfunc=C.pythonapi.PyCFunction_GetFunction
        self.getfunc.argtypes=[C.py_object];self.getfunc.restype=C.c_void_p

    def start(self):
        self.previous=sys.getprofile();assert self.previous is None
        sys.setprofile(self)

    def __call__(self,frame,event,arg):
        if event!='c_call' or getattr(arg,'__name__',None)!='paintEvent':return
        try:
            if not isinstance(arg,types.BuiltinFunctionType):return
            receiver=getattr(arg,'__self__',None)
            if not isinstance(receiver,self.widgets.QLabel):return
            rva=self.getfunc(arg)-self.base
            if rva!=self.entry['entry_rva']:return
            pixmap=receiver.pixmap()
            if pixmap is None or pixmap.isNull():return
            begin=time.perf_counter_ns()
            import shiboken6
            source=Path(frame.f_code.co_filename)
            try:relative=source.resolve().relative_to(self.root.resolve()).as_posix()
            except ValueError:relative=None
            parents=[];node=receiver.parent()
            for _ in range(12):
                if node is None:break
                parents.append(dict(type=type(node).__module__+'.'+type(node).__qualname__,object_name=node.objectName(),
                    preview_member_is_receiver=getattr(node,'_preview',None) is receiver))
                node=node.parent()
            self.rows.append(dict(tid=self.tid(),entry_rva=rva,receiver_type=type(receiver).__module__+'.'+type(receiver).__qualname__,
                receiver_cpp_pointer=shiboken6.getCppPointer(receiver)[0],receiver_object_name=receiver.objectName(),
                caller=dict(file=str(source),relative=relative,function=frame.f_code.co_name,qualname=frame.f_code.co_qualname,
                    line=frame.f_lineno,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
                caller_self_is_receiver=frame.f_locals.get('self') is receiver,parents=parents,
                pixmap=dict(width=pixmap.width(),height=pixmap.height(),dpr=pixmap.devicePixelRatioF(),alpha=pixmap.hasAlphaChannel()),
                widget=dict(width=receiver.width(),height=receiver.height(),dpr=receiver.devicePixelRatioF(),scaled_contents=receiver.hasScaledContents()),
                live_pose_present=getattr(receiver,'_live_pose',None) is not None,
                pre_native_observation_bracket_ns=[begin,time.perf_counter_ns()]))
            if len(self.rows)==self.budget:
                sys.setprofile(self.previous);self.auto_detached=True
        except Exception as exc:
            self.errors.append(repr(exc));sys.setprofile(self.previous)

    def close(self):
        if sys.getprofile() not in (self,self.previous):self.errors.append('Unexpected profiler replacement')
        sys.setprofile(self.previous)
        return dict(rows=self.rows,errors=self.errors,gui_tid=self.gui_tid,budget=self.budget,
            auto_detached=self.auto_detached,final_profile_restored=sys.getprofile() is self.previous,
            scope='Before-call identities only. Observation brackets precede the native call; not native duration, GIL ownership or cost shares.')


def verify(data,entry,formal):
    assert not data['errors'] and data['auto_detached'] and data['final_profile_restored']
    assert len(data['rows'])==data['budget']==3
    for row in data['rows']:
        assert row['tid']==data['gui_tid'] and row['entry_rva']==entry['entry_rva']
        assert row['receiver_cpp_pointer'] and row['pixmap']['width']>0 and row['pixmap']['height']>0
        assert row['pre_native_observation_bracket_ns'][0]<=row['pre_native_observation_bracket_ns'][1]
        name=row['caller']['relative'];assert name in formal and row['caller']['source_sha256']==formal[name]
    return dict(call_identity_pass=True,field_historical_receiver_identified=False,performance_qualification=False)
