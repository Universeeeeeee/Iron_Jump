"""New independent replay wrapper; old replay/finalization entry bytes unchanged."""
from pathlib import Path
import runpy
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from parent import Parent

output=Path(sys.argv[sys.argv.index('--output')+1])
wire=Parent(output,HERE/'sdk_child.py');wire.install()
try:runpy.run_path(str(HERE.parent/'gil_workload_finalization/entry01.py'),run_name='__main__')
finally:
    if (output/'wire').exists():wire.finish()
