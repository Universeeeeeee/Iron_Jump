"""Open the real USB through the child, reach readiness, then discard without a human test."""
import json,sys,os
from pathlib import Path
from qtpy.QtCore import QCoreApplication,QTimer
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
from config.walking_config import WalkingConfig
from client import LiveSessionProcess
if __name__=='__main__':
 plan=json.loads((HERE/'plan15.json').read_text(encoding='utf-8'));os.environ['DAYU_DLL']=plan['dll_path'];app=QCoreApplication([]);runs=HERE/'runs';runs.mkdir(exist_ok=False);client=LiveSessionProcess(runs/'live_discard01');ready=[];closed=[];errors=[];discarded=[]
 def readiness(value):
  if value.get('ready') and not discarded:ready.append(value);discarded.append(True);client.discard()
 client.walking_readiness_changed.connect(readiness);client.closed.connect(lambda value:(closed.append(value),app.quit()));client.failed.connect(lambda value:(errors.append(value),app.quit()))
 client.prepare(WalkingConfig(stop_type='Software command'));QTimer.singleShot(90000,lambda:(errors.append('live_discard_timeout'),app.quit()));app.exec()
 if errors:client.finalize_failure()
 actor_path=runs/'live_discard01/actor/result.json';actor=json.loads(actor_path.read_text()) if actor_path.exists() else None
 result=dict(complete=not errors and len(ready)==len(closed)==1 and closed[0]['complete'] and actor and actor['complete'],errors=errors,readiness_count=len(ready),last_quality_status=client.quality_status,closed=closed,actor=actor,human_test_started=False,session_started=False)
 (HERE/'live_discard01.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));raise SystemExit(not result['complete'])
