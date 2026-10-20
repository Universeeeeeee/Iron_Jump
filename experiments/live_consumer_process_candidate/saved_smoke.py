"""Saved-input lifecycle smoke through the same live actor/client protocol."""
import json,sys
from pathlib import Path
from qtpy.QtCore import QCoreApplication,QTimer
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
from config.walking_config import WalkingConfig
from client import LiveSessionProcess
if __name__=='__main__':
 plan=json.loads((HERE/'plan08.json').read_text(encoding='utf-8'));fixture=Path(plan['fixture_root']);meta=json.loads((fixture/'report.json').read_text(encoding='utf-8'))['report_config_snapshot'];cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
 app=QCoreApplication([]);runs=HERE/'runs';runs.mkdir(exist_ok=False);client=LiveSessionProcess(runs/'smoke01',fixture_root=str(fixture));started=[];reports=[];closed=[];errors=[]
 def ready(value):
  if value.get('ready') and not started and not client._start_pending:client.start(acknowledge_quality=True,quality_key=value['device_key'])
 def armed():started.append(True);QTimer.singleShot(3000,client.stop)
 client.walking_readiness_changed.connect(ready);client.session_started.connect(armed);client.session_finished.connect(reports.append);client.closed.connect(lambda value:(closed.append(value),app.quit()));client.failed.connect(lambda value:(errors.append(value),app.quit()))
 client.prepare(cfg);QTimer.singleShot(60000,lambda:(errors.append('smoke_timeout'),app.quit()));app.exec()
 result=dict(complete=not errors and len(started)==len(reports)==len(closed)==1 and closed[0]['complete'],errors=errors,started=len(started),reports=len(reports),closed=closed)
 (HERE/'smoke01.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));raise SystemExit(not result['complete'])
