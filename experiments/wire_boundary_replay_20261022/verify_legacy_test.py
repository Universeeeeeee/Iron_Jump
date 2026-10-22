"""Isolate the existing all-clear fake-device test from operator QSettings.

Only this Python process is patched. No registry/settings writes or USB opens.
The original unisolated failure remains in tests01.json.
"""
import json
from pathlib import Path
import sys

root = Path('E:/OptoJump/Iron_Jump')
sys.path.insert(0, str(root))
from hardware import known_beams
import pytest

saved = known_beams.load_known_beams()
known_beams.load_known_beams = lambda settings=None: ()
code = pytest.main(['-q', str(root / 'tests/test_overground_walking.py') + '::test_real_usb_worker_monitor_and_stop_run_on_worker_thread'])
assert saved == known_beams.QSettings('IronJump', 'DeviceQuality').value('known_bad_beams', []) or tuple(known_beams.QSettings('IronJump', 'DeviceQuality').value('known_bad_beams', [])) == saved
Path(sys.argv[1]).write_text(json.dumps(dict(exit_code=int(code), original_registered_beams=saved,
    test_condition='All-clear mock input with process-local empty registered-beam provider; real settings unchanged.',
    production_settings_modified=False), indent=2))
raise SystemExit(code)
