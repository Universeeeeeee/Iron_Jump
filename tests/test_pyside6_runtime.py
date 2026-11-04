"""Production package imports must select PySide6, even on dual-binding hosts."""
import os
import subprocess
import sys
import pytest

@pytest.mark.parametrize('entry',['ui','camera.control_service','engine','tools','vision','voice','agent'])
def test_entry_selects_only_pyside6(entry):
    code=f"import {entry}; import qtpy; from qtpy import QtCore; import sys; assert qtpy.API_NAME == 'PySide6'; assert QtCore.QObject.__module__.startswith('PySide6'); assert 'PyQt5.QtCore' not in sys.modules"
    subprocess.run([sys.executable,'-c',code],check=True,env={**os.environ,'QT_API':'pyqt5','QT_PREFERRED_BINDING':'PyQt5','QT_QPA_PLATFORM':'offscreen'})
