"""Mark successful serialization/SDK teardown before optional native exit telemetry."""
import json,runpy,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
out=Path(sys.argv[sys.argv.index('--output')+1])
try:runpy.run_path(str(HERE/'replay.py'),run_name='__main__')
finally:
    if out.exists():
        code=getattr(sys.exc_info()[1],'code',None)
        (out/'complete.json').write_text(json.dumps({'system_exit_code':code,'measurement_serialized':(out/'measurement.json').exists()}))
