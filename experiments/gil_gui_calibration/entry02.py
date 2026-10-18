"""Preserve completion or failure of one independent GUI replay process."""
import json
from pathlib import Path
import runpy
import sys


output=Path(sys.argv[sys.argv.index('--output')+1])
try:runpy.run_path(str(Path(__file__).parent/'replay02.py'),run_name='__main__')
finally:
    if output.exists():
        with (output/'complete.json').open('x') as f:
            json.dump(dict(system_exit_code=getattr(sys.exc_info()[1],'code',None),serialized=(output/'measurement.json').exists()),f,indent=2)
