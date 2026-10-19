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
    from outbox import Outbox,OutboxError
    from clocks import native_anchor
    folder=Path(output_root);folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    app=QCoreApplication([]);source=Source(Path(input_root));meta=source.meta
    controller=SessionController(worker_factory=lambda **kwargs:source)
    probe=QueueProbe(int(source.indices[0]),False,int(source.indices[-1]))
    status={};events=[];errors=[];reports=[];armed=[];sequence=0;prepared=False;ready_sent=False;refs={};command_sequence=0;pending_control=None;completed_control=None
    outbox=Outbox(connection);transport_fault=None;clock_revision=0;clock_marker=None;source_ready_info=None;source_clock_history=[];startup_anchor=native_anchor()
    def emit(kind,payload):
        nonlocal sequence
        sequence+=1
        row=dict(sequence=sequence,pid=os.getpid(),kind=kind,host_ns=time.perf_counter_ns(),payload=payload)
        try:outbox.enqueue(row);accepted=True
        except OutboxError:accepted=False
        events.append(dict(sequence=sequence,kind=kind,host_ns=row['host_ns'],accepted_by_outbox=accepted))
        return accepted
    def request_fault(reason):
        nonlocal transport_fault,pending_control
        if transport_fault is not None:return
        transport_fault=dict(reason=reason,host_ns=time.perf_counter_ns())
        errors.append('ipc_transport_failure:'+reason);outbox.abort('actor_fault:'+reason)
        pending_control=dict(kind='transport_failure',command_sequence=None)
        if controller.is_running:controller.stop('ipc_transport_failure')
        elif controller._thread is not None:controller.discard()
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
            nonlocal prepared,command_sequence,ready_sent,pending_control,completed_control,clock_revision,clock_marker,source_ready_info
            try:
                failure=outbox.snapshot()['failure']
                if failure is not None:request_fault(failure['reason'])
                if transport_fault is None and connection.poll():
                    command=connection.recv()
                    if command['sequence']!=command_sequence+1:raise ValueError('Command sequence changed')
                    command_sequence+=1;kind=command['kind']
                    if kind=='prepare' and not prepared:
                        prepared=True
                        cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
                        controller.prepare(cfg);refs.update(engine=controller._engine,quality=controller._quality,inbox=controller._frame_inbox,thread=controller._thread)
                        emit('prepared',dict(no_hardware=True,external_sdk_ready_required=True))
                    elif kind=='source_ready' and prepared and not source.sdk_ready.is_set():
                        info=command['info']
                        assert info['method']=='tracking_start' and info['code']==0
                        assert info['gui_pid']==os.getppid() and info['sdk_pid']>0 and info['sdk_pid'] not in (os.getpid(),os.getppid())
                        source_ready_info=dict(info);source.sdk_ready.set()
                        emit('source_enabled',dict(command_sequence=command_sequence,sdk_ready=source_ready_info))
                    elif kind=='start' and prepared and ready_sent and not armed:
                        controller.start(acknowledge_quality=True,quality_key=command['quality_key'])
                    elif kind in ('pause','resume','stop','discard') and prepared and pending_control is None:
                        emit('command_received',dict(command_sequence=command_sequence,kind=kind))
                        if kind in ('stop','discard'):pending_control=dict(kind=kind,command_sequence=command_sequence)
                        outcome=apply_control(controller,kind)
                        if outcome['status']=='unsupported':emit('command_rejected',dict(command_sequence=command_sequence,kind=kind,**outcome))
                    else:raise ValueError('Unexpected command phase: '+kind)
                if prepared and source.anchor_ns is not None and source.anchor_ns!=clock_marker:
                    clock_revision+=1;clock_marker=source.anchor_ns
                    value=dict(revision=clock_revision,anchor_ns=source.anchor_ns,original_start_ns=source.original_start_ns,arm_pause_ns=source.arm_pause_ns,armed=bool(armed),observed_ns=time.perf_counter_ns())
                    source_clock_history.append(value);emit('source_anchor',value)
                if prepared and pending_control is None and not ready_sent and status.get('ready') and getattr(controller._frame_inbox,'last_consumed_sample',-1)==meta['device']['checked_sample_index']:
                    ready_sent=True;emit('ready_to_start',dict(quality_key=status['device_key'],completed_sample=controller._frame_inbox.last_consumed_sample))
                if pending_control is not None and (resources_stopped(controller,source,refs.get('thread')) or (not prepared and controller._thread is None and source.reader is None)):
                    QCoreApplication.sendPostedEvents(None,QEvent.MetaCall)
                    completed_control=dict(pending_control)
                    if transport_fault is None:
                        emit('command_completed',dict(**completed_control,reader_stopped=True,qt_thread_stopped=True))
                        if reports:emit('report_value',dict(report=reports[0],raw_exports_child_owned=True))
                    timer.stop();app.quit()
            except BaseException as exc:
                request_fault('command_failure:'+repr(exc))
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
    emit('actor_ready',dict(no_qwidget=True,qpc_anchor=startup_anchor,parent_pid=os.getppid()));app.exec();timer.stop()
    if controller._thread:
        if controller.is_running:controller.stop('ipc_transport_failure' if transport_fault else 'manual')
        else:controller.discard()
    probe.close()
    reader_stopped=source.reader is None or not source.reader.is_alive()
    thread_stopped=not prepared or ('thread' in refs and not refs['thread'].isRunning())
    complete=not errors and completed_control is not None and reader_stopped and thread_stopped and ((completed_control['kind']=='stop' and len(reports)==len(armed)==1) or (completed_control['kind']=='discard' and not reports and not armed))
    if reports:
        report=reports[0]
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        quality=refs['quality'];engine=refs['engine'];runtime=quality._runtime;window_hash=hashlib.sha256()
        for bits,changes in runtime._window:window_hash.update(bits.tobytes());window_hash.update(changes.tobytes())
        state=dict(quality=quality.snapshot(),runtime_counts=runtime._counts.tolist(),runtime_transitions=runtime._transitions.tolist(),runtime_healthy=runtime.healthy_samples,runtime_window_sha256=window_hash.hexdigest(),audit=digest(engine.overground.processor.event_audit),timeline=digest(list(engine.overground.processor.timeline)),mirror_events=engine.overground._frame_filter.mirror_guard.events,raw_archive_sha256=hashlib.sha256(b''.join(engine.overground.frames)).hexdigest())
        (folder/'state.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    if source.delivered:
        np.savez_compressed(folder/'raw_frames.npz',**{k:np.array([getattr(f,a) for f in source.delivered]) for k,a in [('sample_indices','sample_index'),('frame_indices','frame_index'),('received_ns','received_monotonic_ns'),('dropped_frames_before','dropped_frames_before')]},bits=np.array([np.frombuffer(f.contact_bits,np.uint8) for f in source.delivered]),valid_bits=np.array([np.frombuffer(f.valid_bits,np.uint8) for f in source.delivered]),wire=np.array([np.frombuffer(f.wire_payload,np.uint8) for f in source.delivered]))
    emit('payload_end',dict(local_measurement_complete=complete,transport_unconfirmed=True))
    writer_finished=outbox.finish(2)
    if not writer_finished and transport_fault is None:
        transport_fault=dict(reason='writer_finalization_failed',host_ns=time.perf_counter_ns())
        errors.append('ipc_transport_failure:writer_finalization_failed')
    outbox.preserve(folder/'output_snapshot')
    complete=complete and writer_finished and not errors
    result=dict(complete=complete,pid=os.getpid(),errors=errors,events=events,armed=armed,commands_received=command_sequence,source_count=len(source.delivered),expected_source_count=len(source.indices),reader_stopped=reader_stopped,qt_thread_stopped=thread_stopped,controller_released=controller._thread is None,queue_common=probe.common,performance_qualification=False,finite_EOF_poll_exemption=True,application_class=app.metaObject().className(),completed_control=completed_control,transport_fault=transport_fault,outbox=outbox.snapshot(),writer_stop_confirmed=not outbox.thread.is_alive(),report_saved=(folder/'report.json').exists(),process_clock_anchors=[startup_anchor,native_anchor()],source_clock_revisions=clock_revision,source_clock_history=source_clock_history,source_ready_info=source_ready_info,source_arm_error=getattr(source,'arm_error',None),accepted_last_sample=(getattr(refs.get('quality'),'latest_received_frame',None).sample_index if getattr(refs.get('quality'),'latest_received_frame',None) is not None else None))
    with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    connection.close()
    if not complete:raise SystemExit(1)
