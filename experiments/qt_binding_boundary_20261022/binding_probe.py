"""Verify the delivered Qt binding and read target context once before replay."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys


def snapshot():
    import qtpy
    from qtpy import QtCore, QtWidgets
    native = importlib.import_module(qtpy.API_NAME + '.QtCore')
    expected = os.environ['IJ_EXPECTED_QT']
    assert qtpy.API_NAME.lower() == expected
    assert QtCore.QObject.__module__.lower().startswith(expected + '.')
    assert QtWidgets.QApplication.__module__.lower().startswith(expected + '.')
    bindings = sorted({name.split('.')[0] for name in sys.modules if name.startswith(('PyQt5.', 'PyQt6.', 'PySide2.', 'PySide6.'))})
    assert bindings == [qtpy.API_NAME], bindings
    k = c.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.GetPriorityClass.argtypes = [w.HANDLE]
    k.GetPriorityClass.restype = w.DWORD
    k.ProcessIdToSessionId.argtypes = [w.DWORD, c.POINTER(w.DWORD)]
    k.ProcessIdToSessionId.restype = w.BOOL
    session = w.DWORD()
    assert k.ProcessIdToSessionId(os.getpid(), c.byref(session))
    priority = k.GetPriorityClass(k.GetCurrentProcess())
    assert priority, c.get_last_error()
    return dict(pid=os.getpid(), expected=expected, actual=qtpy.API_NAME,
                qt_version=QtCore.qVersion(), qobject_module=QtCore.QObject.__module__,
                qapplication_module=QtWidgets.QApplication.__module__, loaded_bindings=bindings,
                qtcore_path=native.__file__, qtcore_sha256=hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
                session_id=session.value, priority_class=priority,
                qpa_requested=os.environ.get('QT_QPA_PLATFORM'),
                scope='Read once before workload; startup context only, no setters.')


def install_probe(r):
    original = r.install_pipeline
    original_flush = r.flush
    state = {}

    def flush():
        original_flush()
        if state and not state.get('written'):
            out = Path(os.environ['IJ_REPLAY_OUTPUT'])
            with (out / f'binding_{os.getpid()}.json').open('x', encoding='utf-8') as stream:
                json.dump(state['context'], stream, indent=2)
            state['written'] = True

    def install():
        was_installed = r._INSTALLED
        result = original()
        if not was_installed:
            # Parent runner creates its folder after install_pipeline. Keep the
            # record in memory until replay flush rather than precreating it.
            state['context'] = snapshot()
        return result

    r.install_pipeline = install
    r.flush = flush
