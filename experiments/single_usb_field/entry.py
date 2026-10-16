import json,runpy,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;out=Path(sys.argv[sys.argv.index('--output')+1])
try:runpy.run_path(str(HERE/'field_runner.py'),run_name='__main__')
finally:
    if out.exists():(out/'complete.json').write_text(json.dumps({'system_exit_code':getattr(sys.exc_info()[1],'code',None),'serialized':(out/'measurement.json').exists()}))
