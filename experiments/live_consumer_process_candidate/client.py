"""Qt facade for the live child-owned SessionController."""
from dataclasses import asdict
import json,multiprocessing,pickle,threading,time
from pathlib import Path
from qtpy.QtCore import QObject,QTimer,Signal
from actor import json_value,run_actor
from inbox import Inbox
from outbox import Outbox
from protocol import validate_output
from report_artifact import read_report
class LiveSessionProcess(QObject):
 hop_event=Signal(object);jump_quality_notice=Signal(dict);gait_step_event=Signal(object);gait_snapshot=Signal(dict);footprint_visual_frame=Signal(dict);device_message=Signal(str);device_state_changed=Signal(str,str);device_layout_changed=Signal(object);walking_readiness_changed=Signal(dict);led_health_changed=Signal(dict);beam_quality_notice=Signal(dict);pause_state_changed=Signal(bool);session_started=Signal();source_exhausted=Signal();session_finished=Signal(object);closed=Signal(dict);failed=Signal(str)
 def __init__(self,folder,parent=None,batch_size=40,fixture_root=None):
  super().__init__(parent);self.folder=Path(folder);self.batch_size=batch_size;self.fixture_root=fixture_root;self.process=None;self.connection=None;self.writer=None;self.reader=None;self.inbox=Inbox();self.timer=QTimer(self);self.timer.setInterval(5);self.timer.timeout.connect(self._tick);self.sequence=0;self.command_sequence=0;self.report=None;self.terminal=None;self.errors=[];self._running=False;self._start_pending=False;self._device_state='disconnected';self.quality_status={};self.quality_policy=None
 @property
 def is_running(self):return self._running
 @property
 def is_paused(self):return False
 @property
 def device_state(self):return self._device_state
 @property
 def engine(self):return None
 def _send(self,kind,**values):
  self.command_sequence+=1;self.writer.enqueue(dict(sequence=self.command_sequence,kind=kind,**values));return self.command_sequence
 def prepare(self,config):
  if self.process is not None:raise ValueError('One live process per facade')
  self.folder.mkdir(exist_ok=False);(self.folder/'active.lock').mkdir();ctx=multiprocessing.get_context('spawn');self.connection,child=ctx.Pipe();self.process=ctx.Process(target=run_actor,args=(child,str(self.folder/'actor'),self.batch_size,self.fixture_root));self.process.start();child.close();self.writer=Outbox(self.connection);self.reader=threading.Thread(target=self._receive,daemon=True);self.reader.start();self._config=config;self.timer.start()
 def _receive(self):
  detail=None
  try:
   while True:
    try:
     if not self.connection.poll(.2):
      if self.inbox.closed:break
      continue
     packet=self.connection.recv_bytes(self.inbox.max_bytes)
    except (EOFError,OSError) as exc:detail=repr(exc);break
    if not self.inbox.put(packet):break
  finally:self.inbox.ended(detail)
 def _packet(self,message):
  self.sequence=validate_output(message,self.sequence,self.process.pid);kind=message['kind'];value=message['payload']
  if kind=='actor_ready':
   from hardware.beam_quality import BeamQualityPolicy
   policy=self.quality_policy or BeamQualityPolicy();self._send('prepare',config=self._config.to_dict(),quality_policy=asdict(policy))
  elif kind=='readiness':self.quality_status=json_value(value);self.walking_readiness_changed.emit(value)
  elif kind=='snapshot':self.gait_snapshot.emit(value)
  elif kind=='visual':self.footprint_visual_frame.emit(value)
  elif kind=='notification':
   signal=value['signal'];args=value['args']
   if signal=='device_state_changed':self._device_state=args[0]
   getattr(self,signal).emit(*args)
  elif kind=='started':self._start_pending=False;self._running=True;self.session_started.emit()
  elif kind=='source_exhausted':self.source_exhausted.emit()
  elif kind=='command_completed':self._running=False
  elif kind=='report_value':self.report=read_report(self.folder/'actor',value['report_reference'])
  elif kind=='terminal':self.terminal=value
 def _tick(self):
  try:
   for packet in self.inbox.take(16):self._packet(pickle.loads(packet))
   if self.terminal is None:
    if self.process is not None and not self.process.is_alive() and self.inbox.snapshot()['reader_done']:raise RuntimeError('Live actor ended without terminal output')
    return
   if self.process.is_alive():return
   self.process.join(0);self.writer.finish(2);self.inbox.close();self.connection.close();self.reader.join(1);self.timer.stop()
   status=dict(complete=self.terminal['complete'] and not self.terminal['errors'] and self.process.exitcode==0,actor_pid=self.process.pid,actor_exitcode=self.process.exitcode,commands=self.command_sequence,outputs=self.sequence,batch_size=self.batch_size)
   (self.folder/'status.json').write_text(json.dumps(status,indent=2))
   if not status['complete']:raise RuntimeError('Live actor failed: '+repr(self.terminal['errors']))
   if self.report is not None:self.session_finished.emit(self.report)
   self.closed.emit(status)
  except BaseException as exc:self._fail(repr(exc))
 def start(self,*,acknowledge_quality=False,quality_key=None):
  if self._running or self._start_pending:return False
  self._start_pending=True;self._send('start',acknowledge_quality=acknowledge_quality,quality_key=quality_key);return True
 def stop(self,reason='manual'):
  if not self._running:return False
  self._send('stop',reason=reason);return True
 def discard(self):self._send('discard')
 def refresh_led_health(self):self._send('refresh_led_health')
 def retry_device(self):raise NotImplementedError('Create a new live process after retained failure')
 def toggle_pause(self):return False
 def _fail(self,error):
  if self.errors:return
  self.errors.append(error);self.timer.stop();self.inbox.close()
  if self.writer:self.writer.abort('parent_failure');self.writer.finish(1)
  if self.connection:
   try:self.connection.close()
   except OSError:pass
  (self.folder/'failure.json').write_text(json.dumps(dict(error=error,actor_pid=None if self.process is None else self.process.pid,actor_alive=None if self.process is None else self.process.is_alive()),indent=2));self.failed.emit(error)
 def finalize_failure(self,timeout=10):
  if self.process is None:return True
  self.process.join(timeout)
  if self.reader is not None:self.reader.join(1)
  return not self.process.is_alive()
