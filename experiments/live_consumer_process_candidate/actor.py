"""Child-owned original SessionController/UsbWorker with batch40 ground inbox."""
from dataclasses import asdict,is_dataclass
import hashlib,json,os,sys,time,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def _json_default(value):
 if is_dataclass(value):return asdict(value)
 raise TypeError(f'Object of type {value.__class__.__name__} is not JSON serializable')
def json_value(value):
 return json.loads(json.dumps(value,ensure_ascii=False,default=_json_default))
def run_actor(connection,output_root,batch_size=40,fixture_root=None):
 sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
 import numpy as np
 from qtpy.QtCore import QCoreApplication,QObject,QTimer,Slot,QEvent
 from config.walking_config import WalkingConfig
 from config.overground_running_config import OvergroundRunningConfig
 from hardware.beam_quality import BeamQualityPolicy
 from ui.session_controller import SessionController,_GroundFrameInbox
 from protocol import validate_command,NOTIFICATIONS
 from outbox import Outbox,OutboxError
 from queue_probe import QueueProbe
 folder=Path(output_root);folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir();app=QCoreApplication([]);source=None
 if fixture_root is None:controller=SessionController()
 else:
  sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'))
  from replay02 import Source
  source=Source(Path(fixture_root));controller=SessionController(worker_factory=lambda **kwargs:source)
 outbox=Outbox(connection)
 def readers():return [dict(tid=t.native_id,name=t.name) for t in threading.enumerate() if t.name=='CyUsbInterfaceReader']
 sequence=command_sequence=0;prepared=False;reports=[];errors=[];refs={};raw_batches=[];last_readiness=None;probe=None;consumer_tid=None;pending_control=None;completed_control=None;transport_fault=None
 original_drain=_GroundFrameInbox.drain;original_consume=_GroundFrameInbox._consume
 @Slot()
 def drain(inbox):
  deadline=time.perf_counter()+.004
  while True:
   with inbox._lock:items=[inbox._pending.popleft() for _ in range(min(batch_size,len(inbox._pending)))]
   inbox._consume(items)
   if not items or time.perf_counter()>=deadline:break
  with inbox._lock:pending=bool(inbox._pending)
  interval=0 if pending else 5
  if inbox._timer.interval()!=interval:inbox._timer.setInterval(interval)
 def consume(inbox,items):
  nonlocal probe,consumer_tid
  if items:raw_batches.append(items)
  if items and probe is None:
   first=next((value for issue,value in items if not issue),None)
   if first is not None:probe=QueueProbe(first.sample_index,True);probe.start(inbox);consumer_tid=threading.get_native_id()
  return probe.consume(inbox,items,original_consume) if probe is not None else original_consume(inbox,items)
 _GroundFrameInbox.drain=drain;_GroundFrameInbox._consume=consume
 def emit(kind,payload):
  nonlocal sequence,transport_fault
  sequence+=1;row=dict(sequence=sequence,pid=os.getpid(),kind=kind,host_ns=time.perf_counter_ns(),payload=payload)
  try:outbox.enqueue(row)
  except OutboxError as exc:transport_fault=transport_fault or repr(exc);errors.append('output:'+repr(exc))
 def relay(name,*args):emit('notification',dict(signal=name,args=args))
 callbacks=[]
 for name in NOTIFICATIONS:
  callback=lambda *args,_name=name:relay(_name,*args);getattr(controller,name).connect(callback);callbacks.append(callback)
 class Delivery(QObject):
  @Slot(dict)
  def readiness(self,value):
   nonlocal last_readiness
   last_readiness=json_value(value);emit('readiness',value)
  @Slot(dict)
  def snapshot(self,value):emit('snapshot',value)
  @Slot(dict)
  def visual(self,value):emit('visual',value)
  @Slot()
  def started(self):
   if source is not None:source.arm_ready.set()
   emit('started',dict())
  @Slot(object)
  def finished(self,report):
   QCoreApplication.sendPostedEvents(None,QEvent.MetaCall);value=asdict(report);value.pop('export_frames',None);value.pop('export_timestamps',None);reports.append(json.loads(json.dumps(value,ensure_ascii=False)))
  @Slot()
  def commands(self):
   nonlocal command_sequence,prepared,pending_control,completed_control
   try:
    if outbox.snapshot()['failure'] is not None:raise RuntimeError('Output writer failed')
    if connection.poll():
     command=connection.recv();command_sequence=validate_command(command,command_sequence);kind=command['kind'];emit('command_received',dict(sequence=command_sequence,kind=kind))
     if kind=='prepare' and not prepared:
      values=command['config'];cls=WalkingConfig if values['test_type']=='Sprint and Gait Test' else OvergroundRunningConfig
      cfg=cls(**{k:v for k,v in values.items() if k in cls.__dataclass_fields__ and cls.__dataclass_fields__[k].init});controller.quality_policy=BeamQualityPolicy(**command['quality_policy']);controller.prepare(cfg);prepared=True
      refs.update(engine=controller._engine,quality=controller._quality,inbox=controller._frame_inbox,thread=controller._thread,worker=controller._worker)
      if source is not None:source.sdk_ready.set()
      emit('prepared',dict(batch_size=batch_size,fixture=source is not None))
     elif kind=='start' and prepared and not controller.is_running:
      controller.start(acknowledge_quality=command.get('acknowledge_quality',False),quality_key=command.get('quality_key'))
     elif kind=='stop' and controller.is_running:
      pending_control=dict(kind='stop',sequence=command_sequence);controller.stop(command.get('reason','manual'))
     elif kind=='discard' and prepared and not controller.is_running:
      pending_control=dict(kind='discard',sequence=command_sequence);controller.discard()
     elif kind=='refresh_led_health' and prepared:controller.refresh_led_health()
     else:raise ValueError('Unexpected live command phase: '+kind)
    if pending_control and controller._thread is None:
     completed_control=dict(pending_control);emit('command_completed',dict(**completed_control,reader_stopped=True,qt_thread_stopped=True));timer.stop();app.quit()
   except BaseException as exc:errors.append(repr(exc));timer.stop();app.quit()
 delivery=Delivery();controller.walking_readiness_changed.connect(delivery.readiness);controller.gait_snapshot.connect(delivery.snapshot);controller.footprint_visual_frame.connect(delivery.visual);controller.session_started.connect(delivery.started);controller.session_finished.connect(delivery.finished)
 timer=QTimer();timer.setInterval(5);timer.timeout.connect(delivery.commands);timer.start();QTimer.singleShot(900000,lambda:(errors.append('watchdog_timeout'),app.quit()))
 emit('actor_ready',dict(batch_size=batch_size));app.exec();timer.stop()
 if controller._thread is not None:
  try:controller.stop('actor_failure') if controller.is_running else controller.discard()
  except BaseException as exc:errors.append('cleanup:'+repr(exc))
 queue_final=probe.snapshot(refs['inbox']) if probe is not None and 'inbox' in refs else None
 if probe is not None:probe.close()
 raw=[value for items in raw_batches for issue,value in items if not issue]
 issues=[asdict(value) for items in raw_batches for issue,value in items if issue]
 if raw:
  np.savez_compressed(folder/'raw_frames.npz',bits=np.array([np.frombuffer(v.contact_bits,np.uint8) for v in raw]),wire=np.array([np.frombuffer(v.wire_payload,np.uint8) for v in raw]),valid_bits=np.array([np.frombuffer(v.valid_bits,np.uint8) for v in raw]),sample_indices=np.array([v.sample_index for v in raw]),frame_indices=np.array([v.frame_index for v in raw]),received_ns=np.array([v.received_monotonic_ns for v in raw]),dropped_frames_before=np.array([v.dropped_frames_before for v in raw]),stream_ids=np.array([v.stream_id for v in raw]))
  acquisition=dict(issues=issues,frames=[dict(stream_id=v.stream_id,quality_flags=v.quality_flags) for v in raw],layouts={v.stream_id:asdict(v.layout) for v in raw})
  (folder/'acquisition.json').write_text(json.dumps(acquisition,ensure_ascii=False),encoding='utf-8')
 if last_readiness is not None:(folder/'last_readiness.json').write_text(json.dumps(last_readiness,ensure_ascii=False,indent=2),encoding='utf-8')
 if reports:
  report=reports[0];(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False));quality=refs['quality'];engine=refs['engine'];runtime=quality._runtime;window=hashlib.sha256()
  for bits,changes in runtime._window:window.update(bits.tobytes());window.update(changes.tobytes())
  state=dict(quality=quality.snapshot(),runtime_counts=runtime._counts.tolist(),runtime_transitions=runtime._transitions.tolist(),runtime_healthy=runtime.healthy_samples,runtime_window_sha256=window.hexdigest(),event_audit=engine.overground.processor.event_audit,timeline=list(engine.overground.processor.timeline),mirror_events=engine.overground._frame_filter.mirror_guard.events,raw_archive_sha256=hashlib.sha256(b''.join(engine.overground.frames)).hexdigest());(folder/'state.json').write_text(json.dumps(state,ensure_ascii=False))
  emit('report_value',dict(report=report,raw_exports_child_owned=True))
 complete=not errors and completed_control is not None and controller._thread is None and (completed_control['kind']=='discard' or len(reports)==1)
 emit('terminal',dict(complete=complete,errors=errors,batch_size=batch_size));writer_finished=outbox.finish(2);outbox.preserve(folder/'output_snapshot')
 result=dict(complete=complete and writer_finished,pid=os.getpid(),errors=errors,commands_received=command_sequence,completed_control=completed_control,report_saved=(folder/'report.json').exists(),batch_size=batch_size,output=outbox.snapshot(),transport_fault=transport_fault,
  live_default_USB=fixture_root is None,worker_class=None if 'worker' not in refs else refs['worker'].__class__.__module__+'.'+refs['worker'].__class__.__name__,raw_frames_saved=(folder/'raw_frames.npz').exists(),last_readiness=last_readiness,queue_common=[] if probe is None else probe.common,queue_samples=[] if probe is None else probe.samples,queue_final=queue_final,consumer_tid=consumer_tid,readers_after_cleanup=readers(),formal_program_modified=False)
 (folder/'result.json').write_text(json.dumps(result,indent=2));_GroundFrameInbox.drain=original_drain;_GroundFrameInbox._consume=original_consume;connection.close()
 if not result['complete']:raise SystemExit(1)
