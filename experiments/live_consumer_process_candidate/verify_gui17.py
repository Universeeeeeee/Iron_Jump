"""Observe the current real field GUI's final report and close callbacks."""
import hashlib,json,os,sys,threading
from datetime import datetime
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))

def main():
 from qtpy.QtCore import QThread
 from qtpy.QtWidgets import QApplication
 import field_walk as field
 plan=json.loads((HERE/'plan17.json').read_text(encoding='utf-8'));validation=json.loads((HERE/'gui_validation_plan17.json').read_text(encoding='utf-8'));sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
 assert sha(HERE/'plan17.json')==validation['candidate_plan_sha256']
 assert sha(Path(__file__))==validation['observer_sha256']
 assert all(sha(HERE/name)==value for name,value in plan['sources'].items())
 assert all(sha(ROOT/name)==value for name,value in plan['formal_sha256'].items())
 assert sha(Path(plan['dll_path']))==plan['dll_sha256']
 os.environ['DAYU_DLL']=plan['dll_path'];app=QApplication([]);assert app.platformName()=='windows';folder=HERE/'runs'/('gui_walk_'+datetime.now().strftime('%Y%m%d_%H%M%S'));run=field.Run(folder,app,plan);events=[];receipt={};closing={};gui_tid=threading.get_native_id()
 def received(report):
  events.append(dict(kind='report_received',host_ns=field.now(),tid=threading.get_native_id()));path=folder/'client/actor/report.json';disk=json.loads(path.read_text(encoding='utf-8'));receipt.update(full_report_exact=report==disk and run.report==disk,report_bytes=path.stat().st_size,report_sha256=sha(path),on_GUI_thread=QThread.currentThread()==app.thread(),active_contacts=sum(bool(event['active']) for event in report['walking_summary']['event_publications']),metric_steps=len(report['walking_summary']['steps']))
  field.write(folder/'GUI_report_receipt.json',dict(events=events,**receipt))
 def closed(status):
  events.append(dict(kind='closed',host_ns=field.now(),tid=threading.get_native_id()));client=run.client
  closing.update(actor_exitcode=client.process.exitcode,actor_stopped=not client.process.is_alive(),client_running=client.is_running,start_pending=client._start_pending,reader_stopped=not client.reader.is_alive(),writer_stopped=not client.writer.thread.is_alive(),inbox_closed=client.inbox.closed,client_timer_stopped=not client.timer.isActive(),field_timers_stopped=not any(timer.isActive() for timer in (run.timer,run.tail,run.watchdog)),window_closed=not run.window.isVisible(),camera_released=run.panel._capture is None and run.panel._thread is None and not run.panel._preview_active,model_released=run.panel._vision is None,SDK_released=run.panel._control is None and run.panel._closing_control is None and not run.panel._control_stop_failed,status_complete=status['complete'])
 run.client.session_finished.connect(received);run.client.closed.connect(closed);app.exec()
 parent=json.loads((folder/'parent.json').read_text(encoding='utf-8')) if (folder/'parent.json').exists() else {};order=[event['kind'] for event in events];checks=dict(full_report_exact=receipt.get('full_report_exact',False),GUI_thread=receipt.get('on_GUI_thread',False),callbacks_in_order=order==['report_received','closed'],parent_complete=parent.get('complete',False),actor_stopped=closing.get('actor_stopped',False),actor_exit_zero=closing.get('actor_exitcode')==0,client_idle=not closing.get('client_running',True) and not closing.get('start_pending',True),read_write_stopped=closing.get('reader_stopped',False) and closing.get('writer_stopped',False),timers_stopped=closing.get('client_timer_stopped',False) and closing.get('field_timers_stopped',False),window_closed=closing.get('window_closed',False),camera_model_SDK_released=all(closing.get(name,False) for name in ('camera_released','model_released','SDK_released')),close_status_complete=closing.get('status_complete',False))
 result=dict(complete=all(checks.values()),checks=checks,events=events,receipt=receipt,closing=closing,GUI_tid=gui_tid,manual_observation_status='pending human report for this new run',candidate_plan_sha256=validation['candidate_plan_sha256']);field.write(folder/'GUI_validation.json',result)
 if result['complete']:
  from analyze_walk import analyze
  analysis=analyze(folder);code=int(not analysis['complete'])
 else:code=1
 print(json.dumps(dict(folder=str(folder),GUI_validation=result),ensure_ascii=True),flush=True);return code
if __name__=='__main__':raise SystemExit(main())
