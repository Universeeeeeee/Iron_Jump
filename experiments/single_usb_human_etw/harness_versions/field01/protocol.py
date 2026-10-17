"""Low-frequency controller/GUI handshake; no per-frame observers."""
import json,os,time
from pathlib import Path

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(temporary,path)
def mark(root,name,**values):write(root/(name+'.json'),{'host_ns':time.perf_counter_ns(),**values})
def acknowledged(root,case):
    path=root/'trace_ready.json'
    if not path.exists():return False
    value=read(path)
    if value.get('run_id')!=case['run_id'] or value.get('trace')!=case['trace']:raise RuntimeError('ETW handshake does not match this run')
    return True
