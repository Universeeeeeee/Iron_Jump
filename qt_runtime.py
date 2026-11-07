"""Select the sole supported Qt binding before importing desktop libraries."""
import os
import sys

loaded = sys.modules.get('qtpy')
if loaded is not None and getattr(loaded, 'API_NAME', 'PySide6') != 'PySide6':
    raise RuntimeError('本程序仅支持 PySide6，请使用新的 Python 进程启动。')
os.environ['QT_API'] = 'pyside6'
os.environ['QT_PREFERRED_BINDING'] = 'PySide6'
os.environ['PYQTGRAPH_QT_LIB'] = 'PySide6'
