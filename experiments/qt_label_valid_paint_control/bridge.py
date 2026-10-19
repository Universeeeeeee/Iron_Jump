"""Pinned experimental base-call bridge; no production type is patched."""
import ctypes as C
import json
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
import shiboken6


class Bridge:
    def __init__(self):
        qt=Path(QtWidgets.__file__).parent
        native=C.CDLL(str(qt/'Qt6Widgets.dll'))
        helper=C.PyDLL(str(Path(shiboken6.__file__).parent/'shiboken6.abi3.dll'))
        self.original=QtWidgets.QLabel.paintEvent
        self.paint=getattr(native,'?paintEvent@QLabel@@MEAAXPEAVQPaintEvent@@@Z')
        self.paint.argtypes=[C.c_void_p,C.c_void_p];self.paint.restype=None
        self.ctor=getattr(helper,'??0PythonContextMarker@Shiboken@@QEAA@XZ')
        self.ctor.argtypes=[C.c_void_p];self.ctor.restype=C.c_void_p
        self.dtor=getattr(helper,'??1PythonContextMarker@Shiboken@@QEAA@XZ')
        self.dtor.argtypes=[C.c_void_p];self.dtor.restype=None
        audit=json.loads((Path(__file__).parent/'binding_review01.json').read_text())
        for name,fn in [('marker_constructor',self.ctor),('marker_destructor',self.dtor)]:
            code=bytes.fromhex(audit[name]['bytes'])
            assert C.string_at(C.cast(fn,C.c_void_p).value,len(code))==code
        # Keep the original protected call's synchronous Python context. Do not
        # change its setBlocking policy while changing only the GIL boundary.
        self.return_none=helper.Sbk_ReturnFromPython_None
        self.return_none.argtypes=[];self.return_none.restype=C.c_void_p
        self.occurred=getattr(helper,'?occurred@Errors@Shiboken@@YAPEAU_object@@XZ')
        self.occurred.argtypes=[];self.occurred.restype=C.c_void_p
        self.decref=C.pythonapi.Py_DecRef
        self.decref.argtypes=[C.c_void_p];self.decref.restype=None

    def finish(self):
        # PyDLL propagates an actual Python error set by the Shiboken helper.
        # Consume its new reference explicitly; returning py_object here could
        # accidentally retain it in the ctypes conversion layer.
        pointer=self.return_none()
        assert pointer==id(None)
        self.decref(pointer)

    def __call__(self,label,event):
        if not isinstance(label,QtWidgets.QLabel) or not isinstance(event,QtGui.QPaintEvent):
            return self.original(label,event)
        if not shiboken6.isValid(label) or not shiboken6.isValid(event):
            return self.original(label,event)
        app=QtWidgets.QApplication.instance()
        assert app is not None and QtCore.QThread.currentThread()==app.thread()
        # Exact pinned ctor/dtor are TLS-only leaf functions, with no object
        # field accesses. Storage is aligned and remains live through cleanup.
        marker=C.c_uint64()
        address=C.addressof(marker)
        assert self.ctor(address)==address
        try:
            assert self.occurred() is None
            self.paint(shiboken6.getCppPointer(label)[0],shiboken6.getCppPointer(event)[0])
            self.finish()
        finally:
            self.dtor(address)
