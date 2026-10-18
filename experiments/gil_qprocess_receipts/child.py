"""Protocol echo child only. No SDK/model/hardware imports."""
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'gil_wire_receipts'))
from receipts import TextReceipts


output=Path(sys.argv[1]);tap=TextReceipts(sys.stdin);records=[]
def reply(value):print('\nIRON_CAMERA_CONTROL '+json.dumps(value),flush=True)
reply(dict(ready=True))
for line in tap:
    receipt=tap.rows[-1]
    try:value=json.loads(line)
    except Exception as exc:
        records.append(dict(sequence=receipt['sequence'],parsed=False,error=type(exc).__name__))
        reply(dict(tracking_log=dict(event='text_receipt',sequence=receipt['sequence'],parsed=False)));continue
    records.append(dict(sequence=receipt['sequence'],parsed=True))
    if 'method' in value:reply(dict(method=value['method'],result=0))
    else:reply(dict(tracking_log=dict(event='text_receipt',sequence=receipt['sequence'],parsed=True)))
reply(dict(stopped=True))
with output.open('x') as f:json.dump(dict(rows=tap.rows,eof=tap.eof,read_errors=tap.errors,parsed=records),f,indent=2)
