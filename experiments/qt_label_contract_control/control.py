"""Exactly two invalid-paint calls in an isolated offscreen Qt process."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import sys
from check import check

HERE = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


class Row(C.Structure):
    _fields_ = [('tid',C.c_uint32),('phase',C.c_int32),('message_type',C.c_int32),
                ('gil',C.c_int32),('qpc',C.c_int64)]


if __name__ == '__main__':
    assert sys.platform == 'win32' and sys.version_info[:3] == (3,11,5) and C.sizeof(C.c_void_p) == 8
    (HERE/'active.lock').mkdir()
    result = dict(errors=[], handler_restored=False, same_exact_QLabel_native_export=False,
        source_and_modules_match_plan=False, rows=[], call_qpc={}, field_owner_or_root_proven=False)
    try:
        plan = json.loads((HERE/'plan01.json').read_text())
        assert all(sha(HERE/n) == v for n,v in plan['sources'].items())
        assert sha(HERE/'MessageOracle.dll') == plan['dll_sha256']
        assert all(sha(Path(n)) == v for n,v in plan['exact_modules'].items())
        assert plan['call_order'] == ['binding_protected_base','direct_same_native_export']
        assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
        from PySide6 import QtCore, QtGui, QtWidgets
        import shiboken6
        oracle = C.PyDLL(str(HERE/'MessageOracle.dll'))
        oracle.OracleRowSize.argtypes=[]; oracle.OracleRowSize.restype=C.c_int32
        oracle.OracleReset.argtypes=[]; oracle.OracleReset.restype=None
        oracle.OraclePhase.argtypes=[C.c_int32]; oracle.OraclePhase.restype=None
        oracle.OracleCopy.argtypes=[C.POINTER(Row),C.c_int32]; oracle.OracleCopy.restype=C.c_int32
        assert oracle.OracleRowSize() == C.sizeof(Row) == 24
        oracle.OracleReset()
        kernel = C.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentThreadId.argtypes=[]; kernel.GetCurrentThreadId.restype=C.c_uint32
        kernel.QueryPerformanceCounter.argtypes=[C.POINTER(C.c_int64)]; kernel.QueryPerformanceCounter.restype=C.c_int
        def qpc():
            value=C.c_int64(); assert kernel.QueryPerformanceCounter(C.byref(value)); return value.value
        result['gui_tid']=kernel.GetCurrentThreadId()
        qt = Path(QtWidgets.__file__).parent
        core = C.CDLL(str(qt/'Qt6Core.dll'))
        native = C.CDLL(str(qt/'Qt6Widgets.dll'))
        install = getattr(core, plan['qInstallMessageHandler_export'])
        install.argtypes=[C.c_void_p]; install.restype=C.c_void_p
        paint = getattr(native,'?paintEvent@QLabel@@MEAAXPEAVQPaintEvent@@@Z')
        paint.argtypes=[C.c_void_p,C.c_void_p]; paint.restype=None
        result['same_exact_QLabel_native_export']=True
        result['source_and_modules_match_plan']=True
        app=QtWidgets.QApplication([])
        class Label(QtWidgets.QLabel): pass
        label=Label('x')
        callback=C.cast(oracle.OracleMessage,C.c_void_p).value
        previous=install(callback)
        try:
            for phase in (1,2):
                event=QtGui.QPaintEvent(label.rect())
                oracle.OraclePhase(phase)
                begin=qpc()
                if phase==1:
                    QtWidgets.QLabel.paintEvent(label,event)
                else:
                    paint(shiboken6.getCppPointer(label)[0],shiboken6.getCppPointer(event)[0])
                end=qpc()
                oracle.OraclePhase(0)
                result['call_qpc'][str(phase)]=[begin,end]
        finally:
            oracle.OraclePhase(0)
            result['handler_restored']=install(previous)==callback
        buffer=(Row*32)(); count=oracle.OracleCopy(buffer,32); assert 0<=count<=32
        result['rows']=[{name:getattr(r,name) for name,_ in Row._fields_} for r in buffer[:count]]
        label.deleteLater(); QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        result['qualification']=check(result)
    except Exception as exc:
        result['errors'].append(repr(exc))
    result['passed']=not result['errors'] and result.get('qualification',{}).get('contract_control_pass',False)
    result['plan_sha256']=sha(HERE/'plan01.json')
    result['scope']='One offscreen synthetic process, exactly two expected invalid-paint calls; no image, real program, model, device, trace or performance A/B.'
    with (HERE/'result01.json').open('x') as f: json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 2)
