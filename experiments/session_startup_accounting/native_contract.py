"""Native return/exception preservation controls; no model or compute workload."""
import ctypes
import hashlib
import json
from pathlib import Path
from ledger import NativeReader,Ledger
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    assert ctypes.sizeof(ctypes.c_void_p)==8,'This experiment uses the unified Win64 ABI'
    reader=NativeReader();sentinel=object();a=Ledger(reader);returned=a.wrap_open(lambda obj:sentinel)(object())
    error=RuntimeError('native-control-original-error');b=Ledger(reader);got=None
    def fail(obj):raise error
    try:b.wrap_open(fail)(object())
    except RuntimeError as exc:got=exc
    checks=dict(return_identity_preserved=returned is sentinel,original_exception_identity_preserved=got is error,native_reads_valid=all(r['valid'] for r in a.rows+b.rows))
    result=dict(passed=all(checks.values()),checks=checks,return_control=a.payload(),exception_control=b.payload(),pointer_bytes=ctypes.sizeof(ctypes.c_void_p),reader_sha256=hashlib.sha256((HERE/'ledger.py').read_bytes()).hexdigest(),model_orhardware_started=False,actual_load_disturbance_pass=False)
    with (HERE/'native_contract01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(passed=result['passed'],checks=checks)));raise SystemExit(not result['passed'])
