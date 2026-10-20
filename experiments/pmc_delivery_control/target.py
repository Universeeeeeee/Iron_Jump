"""Bind unchanged native delivery control to this process/thread and clock."""
import json
import os
from pathlib import Path
import threading
from winapi import anchor,current_thread
import probe

HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    record=dict(pid=os.getpid(),tid=threading.get_native_id(),before=current_thread(),clock_before=anchor())
    code=None
    try:code=probe.run()
    finally:
        record.update(returncode=code,clock_after=anchor(),after=current_thread())
        with (HERE/'target01.json').open('x') as f:json.dump(record,f,indent=2)
    raise SystemExit(code)
