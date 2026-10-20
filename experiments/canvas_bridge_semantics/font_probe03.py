"""Font-call diagnostics in the same post-QApplication scope as the control."""
import hashlib
import json
from pathlib import Path
from PySide6 import QtCore,QtWidgets
from font_probe import delivery

if __name__=='__main__':
    here=Path(__file__).resolve().parent;output=here/'font_preflight03';output.mkdir()
    result=dict(errors=[],Qt_messages=[],handler_restored=False,font_delivery_pass=False)
    app=QtWidgets.QApplication([])
    def handler(kind,context,message):result['Qt_messages'].append(dict(kind=str(kind),message=message))
    previous=QtCore.qInstallMessageHandler(handler)
    try:result.update(delivery(app,output))
    except Exception as exc:result['errors'].append(repr(exc))
    finally:result['handler_restored']=QtCore.qInstallMessageHandler(previous) is handler
    result['passed']=result['font_delivery_pass'] and not result['errors'] and not result['Qt_messages'] and result['handler_restored']
    result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with (here/'font_preflight03.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 2)
