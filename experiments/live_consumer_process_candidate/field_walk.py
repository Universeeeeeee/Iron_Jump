"""One steady-state real single-USB Walk with physical preview and GUI paint evidence."""
import argparse,json,os,sys,threading,time,traceback
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
from qtpy.QtCore import QEvent,QEventLoop,QObject,QTimer,Qt,Slot
from qtpy.QtWidgets import QApplication,QCheckBox,QHBoxLayout,QLabel,QPushButton,QScrollArea,QVBoxLayout,QWidget
from config.walking_config import WalkingConfig
from client import LiveSessionProcess
from ui.annotation_canvas import AnnotationCanvas
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.ground_track import GroundChannelWidget
from ui.views.execution_view import ExecutionView
from camera.control_service import CameraControlService

def now():return time.perf_counter_ns()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def structure(value):return {name:getattr(value,name) for name,_ in value._fields_}

class Run(QObject):
 def __init__(self,output,app,plan):
  super().__init__();self.output=output;self.app=app;self.plan=plan;self.errors=[];self.sdk_errors=[];self.sdk_events=[];self.sdk={'starts':0,'stops':0,'nonzero_speeds':0};self.reasons=Counter();self.status={};self.started_ns=None;self.stop_requested_ns=None;self.record_path=None;self.record_begin_ns=None;self.last_valid_draw=0;self.body_since=None;self.pose_since=None;self.visual_receipts={};self.paints={};self.closed=[];self.report=None;self.finishing=False;self.cancelled=False
  output.mkdir(parents=True,exist_ok=False);(output/'active.lock').mkdir()
  original_control=CameraControlService.__init__;self.original_control=original_control
  def control_init(control,*args,**kwargs):
   original_control(control,*args,**kwargs)
   def completed(method,code):
    self.sdk_events.append(dict(host_ns=now(),completed=method,result=code))
    if code<0:self.sdk_errors.append([method,code])
    if method=='tracking_start' and code==0:self.sdk['starts']+=1
    if method=='tracking_stop' and code==0:self.sdk['stops']+=1
   def event(value):
    self.sdk_events.append(dict(host_ns=now(),event=value))
    if value.get('event')=='tracking_decision':self.reasons[value.get('reason','unknown')]+=1
    if value.get('event')=='sdk_call' and value.get('method')=='set_speed' and any(value['args']):self.sdk['nonzero_speeds']+=1
   control.completed.connect(completed);control.failed.connect(self.sdk_errors.append);control.tracking_event.connect(event)
  CameraControlService.__init__=control_init
  self.visual={'renders':0,'pose_draw_calls':0,'valid_pose_draws':0};self.original_render=EmbeddedCameraPanel._render_frame
  def render(panel,frame):self.visual['renders']+=1;return self.original_render(panel,frame)
  EmbeddedCameraPanel._render_frame=render
  self.original_draw=AnnotationCanvas._draw_live_pose
  def draw(canvas,painter,rect):
   overlay=canvas._live_pose[0];nodes=overlay['nodes'];stamp=now();links=sum(nodes[a]['valid'] and nodes[b]['valid'] for a,b in overlay['connections']);self.visual['pose_draw_calls']+=1;self.visual['valid_pose_draws']+=int(links>0)
   if links>=6:
    if stamp-self.last_valid_draw>300_000_000:self.pose_since=stamp
    self.last_valid_draw=stamp
   else:self.pose_since=None
   return self.original_draw(canvas,painter,rect)
  AnnotationCanvas._draw_live_pose=draw
  self.original_paint=GroundChannelWidget.paintEvent
  def paint(widget,event):
   self.original_paint(widget,event)
   if hasattr(self,'view') and widget is self.view._ground_track.channel:
    stamp=now()
    for foot in widget._feet+widget.history:
     cid=foot.get('contact_id')
     if cid is not None and foot.get('status')=='confirmed' and str(cid) not in self.paints:self.paints[str(cid)]=stamp
  GroundChannelWidget.paintEvent=paint
  self.window=QWidget();self.window.setWindowTitle('稳定态单 USB Walk · consumer process + batch40');self.window.installEventFilter(self);area=app.primaryScreen().availableGeometry();self.window.resize(min(1180,area.width()-30),min(820,area.height()-30));self.window.setStyleSheet('background:#0d121a;color:#e0e0e0;font-size:17px;')
  layout=QVBoxLayout(self.window);self.banner=QLabel('准备中：站在光栅外，保持全身入镜。设备无需重启。');self.banner.setWordWrap(True);layout.addWidget(self.banner);self.confirm=QCheckBox('确认：全身入镜、光栅空场，且 Windows 录屏已开始（如需）');layout.addWidget(self.confirm);self.start_button=QPushButton('开始一次稳定态 Walk（5 秒空场倒计时）');self.start_button.setEnabled(False);self.start_button.clicked.connect(self.start);layout.addWidget(self.start_button);self.clear_button=QPushButton('走完并从跑道外离开后点击：保留 15 秒空场尾段');self.clear_button.setEnabled(False);self.clear_button.clicked.connect(self.clear);layout.addWidget(self.clear_button);self.cancel_button=QPushButton('取消并保留本轮证据');self.cancel_button.clicked.connect(self.cancel);layout.addWidget(self.cancel_button)
  scroll=QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll,1);content=QWidget();body=QHBoxLayout(content);scroll.setWidget(content);self.view=ExecutionView();body.addWidget(self.view,4);body.addWidget(self.view._ground_track,1)
  self.cfg=WalkingConfig(stop_type='Software command');self.view.configure(self.cfg);self.view._camera_start_timer.stop();self.view.set_quality_preflight_required(True);self.view.btn_start.hide();self.panel=self.view._camera_panel;self.panel.setEnabled(True);self.panel.set_camera_type('tinyse');self.panel._show_pose_action.setChecked(True);self.panel._chk_sdk_tracking.setChecked(True)
  for button in (self.view.btn_logi_camera,self.view.btn_tinyse_camera,self.view.btn_basic_camera):button.setEnabled(False)
  self.client=LiveSessionProcess(output/'client',batch_size=40);self.client.device_state_changed.connect(self.view.on_device_state);self.client.device_layout_changed.connect(self.view.on_device_layout);self.client.walking_readiness_changed.connect(self.view.on_walking_readiness);self.client.beam_quality_notice.connect(self.view.on_beam_quality_notice);self.client.session_started.connect(self.view.on_session_started);self.client.gait_snapshot.connect(self.view.on_gait_snapshot);self.client.device_message.connect(self.view.on_device_message);self.client.footprint_visual_frame.connect(self.on_visual_frame);self.client.footprint_visual_frame.connect(self.view.on_footprint_visual_frame);self.client.walking_readiness_changed.connect(self.ready);self.client.session_started.connect(self.armed);self.client.session_finished.connect(self.finished);self.client.closed.connect(self.done);self.client.failed.connect(self.failed);self.view.stop_requested.connect(self.stop)
  self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.progress);self.tail=QTimer(self);self.tail.setSingleShot(True);self.tail.timeout.connect(self.stop);self.watchdog=QTimer(self);self.watchdog.setSingleShot(True);self.watchdog.timeout.connect(self.timeout)
  self.window.show();self.panel.start_preview();self.client.quality_policy=None;self.client.prepare(self.cfg);self.timer.start();self.watchdog.start(300000)
 @Slot(dict)
 def ready(self,value):self.status=value
 @Slot(dict)
 def on_visual_frame(self,value):
  stamp=now()
  for foot in value.get('feet',[]):
   cid=foot.get('contact_id')
   if cid is not None and foot.get('status')=='confirmed' and str(cid) not in self.visual_receipts:self.visual_receipts[str(cid)]=stamp
 @Slot()
 def progress(self):
  stamp=now();capture=self.panel._capture
  if self.started_ns is None:
   if capture is not None and capture._running and self.record_path is None and self.sdk['starts']:
    self.record_begin_ns=stamp;self.record_path=capture.start_record(self.output/'camera',preserve_raw=True)
   pose,state,_=self.panel._vision.display_state() if self.panel._vision is not None else (None,'disabled',None);landmarks=getattr(pose,'landmarks_33',None);full=bool(landmarks and all(landmarks[k].quality>=.65 and 0<=landmarks[k].x<=1 and 0<=landmarks[k].y<=1 for k in (0,11,12,23,24,25,26,27,28)))
   if full:
    if self.body_since is None:self.body_since=stamp
   else:self.body_since=None
   drawn=self.pose_since is not None and stamp-self.pose_since>=2_000_000_000 and stamp-self.last_valid_draw<=1_000_000_000;record=structure(capture._capture.record_stats()) if self.record_path else None;ready=bool(self.status.get('ready') and self.sdk['starts'] and full and self.body_since and stamp-self.body_since>=2_000_000_000 and drawn and record and record['frames_written']>0 and Path(self.record_path).stat().st_size>0)
   self.start_button.setEnabled(ready and self.confirm.isChecked());self.banner.setText(f"稳定态准备：USB={self.status.get('ready',False)} 全身={full} 骨架持续={drawn} 录像帧={record['frames_written'] if record else 0}。确认后点击开始；不要重启设备。")
  else:
   elapsed=(stamp-self.started_ns)/1e9
   if elapsed<5:self.banner.setText(f'保持光栅空场，还需 {5-elapsed:.1f} 秒')
   elif not self.tail.isActive():self.banner.setText('现在左脚迈入，完成一次 Walk，从跑道外离开；走完后点击上方尾段按钮。')
 @Slot()
 def start(self):
  if self.started_ns is None and self.start_button.isEnabled():self.start_button.setEnabled(False);self.confirm.setEnabled(False);self.client.start(acknowledge_quality=True,quality_key=self.status['device_key'])
 @Slot()
 def armed(self):self.started_ns=now();self.clear_button.setEnabled(True);self.start_button.hide();self.watchdog.start(120000);QTimer.singleShot(5000,QApplication.beep);write(self.output/'armed.json',dict(host_ns=self.started_ns,actor_pid=self.client.process.pid,batch_size=40,cold_start_acceptance=False))
 @Slot()
 def clear(self):
  if self.started_ns is None or now()-self.started_ns<5_000_000_000:return
  self.clear_button.setEnabled(False);self.banner.setText('已标记离场：保持空场 15 秒。');self.tail.start(15000)
 @Slot()
 def stop(self):
  if self.client.is_running:self.stop_requested_ns=now();self.timer.stop();self.tail.stop();self.watchdog.stop();self.banner.setText('正在停止并保存完整证据……');self.client.stop('manual')
 @Slot(object)
 def finished(self,report):self.report=report
 @Slot(dict)
 def done(self,status):self.closed.append(status);self.finalize()
 @Slot(str)
 def failed(self,error):self.errors.append(error);self.client.finalize_failure();self.finalize()
 def cancel(self,*args):
  if self.finishing:return
  self.cancelled=True;self.errors.append('operator_cancel')
  if self.client.is_running:self.stop()
  elif self.client.process is not None:self.client.discard()
  else:self.finalize()
 def timeout(self):self.errors.append('watchdog_timeout');self.cancel()
 def eventFilter(self,watched,event):
  if watched is self.window and event.type()==QEvent.Close and not self.finishing:event.ignore();self.cancel();return True
  return False
 def finalize(self):
  if self.finishing:return
  self.finishing=True;self.timer.stop();self.tail.stop();self.watchdog.stop();record=None
  try:
   if self.record_path and self.panel._capture:self.panel._capture.stop_record(wait=True);record=structure(self.panel._capture.last_record_stats)
  except BaseException as exc:self.errors.append('record_stop:'+repr(exc))
  try:
   self.panel.shutdown();control=self.panel._closing_control
   if control is not None:
    loop=QEventLoop();control.closed.connect(loop.quit);QTimer.singleShot(6000,loop.quit);loop.exec()
   if self.panel._closing_control is not None or self.panel._control_stop_failed:self.errors.append('SDK close unconfirmed')
  except BaseException as exc:self.errors.append('camera_close:'+repr(exc))
  CameraControlService.__init__=self.original_control;EmbeddedCameraPanel._render_frame=self.original_render;AnnotationCanvas._draw_live_pose=self.original_draw;GroundChannelWidget.paintEvent=self.original_paint
  complete=bool(not self.errors and not self.sdk_errors and len(self.closed)==1 and self.closed[0]['complete'] and self.report is not None and self.record_path and record and self.sdk['starts'] and self.sdk['stops'])
  result=dict(complete=complete,errors=self.errors,cancelled=self.cancelled,started_ns=self.started_ns,stop_requested_ns=self.stop_requested_ns,closed=self.closed,report_received=self.report is not None,visual_first_receipt_ns=self.visual_receipts,paint_first_ns=self.paints,visual=self.visual,SDK=self.sdk,SDK_reasons=self.reasons,SDK_errors=self.sdk_errors,record_path=None if self.record_path is None else str(self.record_path),record_stats=record,formal_program_modified=False,cold_start_acceptance=False)
  write(self.output/'parent.json',result);write(self.output/'SDK_events.json',self.sdk_events);self.window.close();self.app.quit()

def main(output):
 plan=json.loads((HERE/'plan16.json').read_text(encoding='utf-8'));os.environ['DAYU_DLL']=plan['dll_path'];app=QApplication([]);run=Run(output,app,plan)
 try:app.exec()
 except BaseException as exc:run.errors.append(''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)));run.cancel()
 return 0 if (output/'parent.json').exists() and json.loads((output/'parent.json').read_text(encoding='utf-8'))['complete'] else 1
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);raise SystemExit(main(parser.parse_args().output))
