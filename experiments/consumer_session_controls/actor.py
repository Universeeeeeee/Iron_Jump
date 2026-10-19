"""Saved-input-only measurement actor using the original controller and Qt thread."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]

def run_actor(connection,input_root,output_root):
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'))
    import numpy as np
    from qtpy.QtCore import QCoreApplication,QObject,QTimer,Slot,Qt,QEvent
    from replay02 import Source
    from queue_probe import QueueProbe
    from ui.session_controller import SessionController,_GroundFrameInbox
    from engine.device_quality_session import DeviceQualitySession
    from engine.overground_session import OvergroundSession
    from config.walking_config import WalkingConfig
    from semantics02 import digest
    from commands import apply_control,resources_stopped,bind_notifications
    folder=Path(output_root);folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    app=QCoreApplication([]);source=Source(Path(input_root));meta=source.meta
    controller=SessionController(worker_factory=lambda **kwargs:source)
    probe=QueueProbe(int(source.indices[0]),False,int(source.indices[-1]))
    status={};events=[];errors=[];reports=[];armed=[];sequence=0;prepared=False;ready_sent=False;refs={};command_sequence=0;pending_control=None;completed_control=None
    def emit(kind,payload):
        nonlocal sequence
        sequence+=1
        row=dict(sequence=sequence,pid=os.getpid(),kind=kind,host_ns=time.perf_counter_ns(),payload=payload)
        connection.send(row);events.append(dict(sequence=sequence,kind=kind,host_ns=row['host_ns']))
    original_consume=_GroundFrameInbox._consume
    def consume(inbox,items):return probe.consume(inbox,items,original_consume)
    _GroundFrameInbox._consume=consume
    # Same finite-saved-source EOF exemption as the existing GUI replay.
    for cls in (DeviceQualitySession,OvergroundSession):
        original=cls.poll
        def poll(self,_original=original):
            if getattr(source,'exhausted_ns',None) is None:return _original(self)
        cls.poll=poll
    class Delivery(QObject):
        @Slot(dict)
        def readiness(self,value):status.clear();status.update(value);emit('readiness',value)
        @Slot(dict)
        def visual(self,value):emit('visual',value)
        @Slot(dict)
        def snapshot(self,value):emit('snapshot',value)
        @Slot()
        def started(self):armed.append(time.perf_counter_ns());source.arm_ready.set();emit('started',dict(checked_sample=meta['device']['checked_sample_index']))
        @Slot(object)
        def finished(self,report):
            # Original stop has joined the measurement thread. Deliver its pending
            # main-thread Qt relays before publishing the terminal report value.
            QCoreApplication.sendPostedEvents(None,QEvent.MetaCall)
            value=asdict(report);value.pop('export_frames',None);value.pop('export_timestamps',None)
            value=json.loads(json.dumps(value,ensure_ascii=False));reports.append(value)
            # Completion is emitted by the command loop after resource checks.
        @Slot()
        def exhausted(self):
            def settle():
                if getattr(controller._frame_inbox,'last_consumed_sample',-1)<int(source.indices[-1]):QTimer.singleShot(20,settle);return
                emit('drained_eof',dict(completed_sample=controller._frame_inbox.last_consumed_sample,received_sample=int(source.indices[-1])))
                # Parent must explicitly request stop after this drain boundary.
            settle()
        @Slot()
        def commands(self):
            nonlocal prepared,command_sequence,ready_sent,pending_control,completed_control
            try:
                if connection.poll():
                    command=connection.recv()
                    if command['sequence']!=command_sequence+1:raise ValueError('Command sequence changed')
                    command_sequence+=1;kind=command['kind']
                    if kind=='prepare' and not prepared:
                        prepared=True
                        cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
                        controller.prepare(cfg);refs.update(engine=controller._engine,quality=controller._quality,inbox=controller._frame_inbox,thread=controller._thread)
                        source.sdk_ready.set()  # Delivery fixture only: no camera or SDK is opened.
                        emit('prepared',dict(no_hardware=True,no_vision_or_sdk=True))
                    elif kind=='start' and prepared and ready_sent and not armed:
                        controller.start(acknowledge_quality=True,quality_key=command['quality_key'])
                    elif kind in ('pause','resume','stop','discard') and prepared and pending_control is None:
                        emit('command_received',dict(command_sequence=command_sequence,kind=kind))
                        if kind in ('stop','discard'):pending_control=dict(kind=kind,command_sequence=command_sequence)
                        outcome=apply_control(controller,kind)
                        if outcome['status']=='unsupported':emit('command_rejected',dict(command_sequence=command_sequence,kind=kind,**outcome))
                    else:raise ValueError('Unexpected command phase: '+kind)
                if prepared and pending_control is None and not ready_sent and status.get('ready') and getattr(controller._frame_inbox,'last_consumed_sample',-1)==meta['device']['checked_sample_index']:
                    ready_sent=True;emit('ready_to_start',dict(quality_key=status['device_key'],completed_sample=controller._frame_inbox.last_consumed_sample))
                if pending_control is not None and resources_stopped(controller,source,refs.get('thread')):
                    QCoreApplication.sendPostedEvents(None,QEvent.MetaCall)
                    completed_control=dict(pending_control)
                    emit('command_completed',dict(**completed_control,reader_stopped=True,qt_thread_stopped=True))
                    if reports:emit('report_value',dict(report=reports[0],raw_exports_child_owned=True))
                    timer.stop();app.quit()
            except BaseException as exc:
                errors.append(repr(exc));timer.stop();app.quit()
    delivery=Delivery()
    controller.walking_readiness_changed.connect(delivery.readiness)
    controller.footprint_visual_frame.connect(delivery.visual)
    controller.gait_snapshot.connect(delivery.snapshot)
    controller.session_started.connect(delivery.started);controller.session_finished.connect(delivery.finished)
    source.exhausted.connect(delivery.exhausted,Qt.QueuedConnection)
    notification_callbacks=bind_notifications(controller,emit)
    timer=QTimer();timer.setInterval(5);timer.timeout.connect(delivery.commands);timer.start()
    def timeout():errors.append('watchdog_timeout');app.quit()
    QTimer.singleShot(90000,timeout)
    emit('actor_ready',dict(no_qwidget=True));app.exec();timer.stop()
    if controller._thread:
        if controller.is_running:controller.stop('manual')
        else:controller.discard()
    probe.close()
    reader_stopped=source.reader is None or not source.reader.is_alive()
    thread_stopped='thread' in refs and not refs['thread'].isRunning()
    complete=not errors and completed_control is not None and reader_stopped and thread_stopped and ((completed_control['kind']=='stop' and len(reports)==len(armed)==1) or (completed_control['kind']=='discard' and not reports and not armed))
    if complete and reports:
        report=reports[0]
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        quality=refs['quality'];engine=refs['engine'];runtime=quality._runtime;window_hash=hashlib.sha256()
        for bits,changes in runtime._window:window_hash.update(bits.tobytes());window_hash.update(changes.tobytes())
        state=dict(quality=quality.snapshot(),runtime_counts=runtime._counts.tolist(),runtime_transitions=runtime._transitions.tolist(),runtime_healthy=runtime.healthy_samples,runtime_window_sha256=window_hash.hexdigest(),audit=digest(engine.overground.processor.event_audit),timeline=digest(list(engine.overground.processor.timeline)),mirror_events=engine.overground._frame_filter.mirror_guard.events,raw_archive_sha256=hashlib.sha256(b''.join(engine.overground.frames)).hexdigest())
        (folder/'state.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    if source.delivered:
        np.savez_compressed(folder/'raw_frames.npz',**{k:np.array([getattr(f,a) for f in source.delivered]) for k,a in [('sample_indices','sample_index'),('frame_indices','frame_index'),('received_ns','received_monotonic_ns'),('dropped_frames_before','dropped_frames_before')]},bits=np.array([np.frombuffer(f.contact_bits,np.uint8) for f in source.delivered]),valid_bits=np.array([np.frombuffer(f.valid_bits,np.uint8) for f in source.delivered]),wire=np.array([np.frombuffer(f.wire_payload,np.uint8) for f in source.delivered]))
    result=dict(complete=complete,pid=os.getpid(),errors=errors,events=events,armed=armed,commands_received=command_sequence,source_count=len(source.delivered),expected_source_count=len(source.indices),reader_stopped=reader_stopped,qt_thread_stopped=thread_stopped,controller_released=controller._thread is None,queue_common=probe.common,performance_qualification=False,finite_EOF_poll_exemption=True,application_class=app.metaObject().className(),completed_control=completed_control,source_arm_error=getattr(source,'arm_error',None),accepted_last_sample=(getattr(refs.get('quality'),'latest_received_frame',None).sample_index if getattr(refs.get('quality'),'latest_received_frame',None) is not None else None))
    with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    emit('terminal',dict(complete=complete,errors=errors));connection.close()
    if not complete:raise SystemExit(1)
