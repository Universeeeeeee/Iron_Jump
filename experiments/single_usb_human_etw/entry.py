import runpy,sys
from pathlib import Path
from protocol import write
HERE=Path(__file__).resolve().parent
out=Path(sys.argv[sys.argv.index('--output')+1])
try:runpy.run_path(str(HERE/'human_runner.py'),run_name='__main__')
finally:
    if out.exists():write(out/'complete.json',{'system_exit_code':getattr(sys.exc_info()[1],'code',None),'serialized':(out/'measurement.json').exists()})
