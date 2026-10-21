"""Reproduce final report delivery with the retained large field report; no devices."""
import hashlib,json,os,shutil,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))

def report_actor(connection,output_root,batch_size,fixture_root):
 from outbox import Outbox
 from report_artifact import report_reference
 plan=json.loads((HERE/'plan17.json').read_text(encoding='utf-8'));folder=Path(output_root);folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir();shutil.copyfile(plan['retained_field_report'],folder/'report.json');box=Outbox(connection)
 box.enqueue(dict(sequence=1,pid=os.getpid(),kind='report_value',payload=dict(report_reference=report_reference(folder))))
 box.enqueue(dict(sequence=2,pid=os.getpid(),kind='terminal',payload=dict(complete=True,errors=[])))
 finished=box.finish(5);(folder/'transport.json').write_text(json.dumps(dict(complete=finished,output=box.snapshot()),indent=2),encoding='utf-8');connection.close()
 if not finished:raise SystemExit(1)

def main():
 import client
 from qtpy.QtCore import QCoreApplication,QTimer
 plan=json.loads((HERE/'plan17.json').read_text(encoding='utf-8'));source=Path(plan['retained_field_report']);assert hashlib.sha256(source.read_bytes()).hexdigest()==plan['retained_field_report_sha256'];assert source.stat().st_size>8*1024*1024
 client.run_actor=report_actor;app=QCoreApplication([]);session=client.LiveSessionProcess(HERE/'runs/report_handoff17');reports=[];closed=[];errors=[];session.folder.parent.mkdir(exist_ok=True)
 session.session_finished.connect(reports.append);session.closed.connect(lambda value:(closed.append(value),app.quit()));session.failed.connect(lambda value:(errors.append(value),app.quit()))
 session.prepare(None);QTimer.singleShot(30000,lambda:(session._fail('report_handoff_timeout'),app.quit()));app.exec()
 if errors:session.finalize_failure()
 expected=json.loads(source.read_text(encoding='utf-8'));transport=json.loads((session.folder/'actor/transport.json').read_text(encoding='utf-8'));result=dict(complete=not errors and len(reports)==len(closed)==1 and closed[0]['complete'] and reports[0]==expected and transport['complete'],errors=errors,report_bytes=source.stat().st_size,report_exact=reports==[expected],closed=closed,transport=transport,USB_camera_human_started=False,original_failed_field_run_reclassified=False)
 (HERE/'report_handoff17.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));return int(not result['complete'])
if __name__=='__main__':raise SystemExit(main())
