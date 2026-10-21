"""Own the original controller, USB reader and batch40 inbox in a child."""
import json
import os
from pathlib import Path
import threading
import time


def run_actor(connection, output_root, worker_factory=None):
    from qtpy.QtCore import QCoreApplication, QObject, QTimer, QEvent, Slot
    from config.test_config import config_from_dict
    from hardware.beam_quality import BeamQualityPolicy
    from ui.session_controller import SessionController
    from .artifacts import save_report
    from .outbox import Outbox, OutboxError
    from .protocol import COMMANDS, NOTIFICATIONS, validate

    folder = Path(output_root)
    folder.mkdir(exist_ok=False)
    (folder / 'active.lock').mkdir()
    app = QCoreApplication([])
    controller = SessionController(worker_factory=worker_factory, ground_batch_size=40)
    outbox = Outbox(connection)
    sequence = command_sequence = 0
    prepared = False
    refs, reports, errors = {}, [], []
    pending = completed = None

    def emit(kind, payload):
        nonlocal sequence
        sequence += 1
        try:
            outbox.enqueue(dict(sequence=sequence, pid=os.getpid(), kind=kind,
                                host_ns=time.perf_counter_ns(), payload=payload))
        except OutboxError as exc:
            errors.append('output:' + repr(exc))

    callbacks = []
    for name in NOTIFICATIONS:
        callback = lambda *args, _name=name: emit('notification', dict(signal=_name, args=args))
        getattr(controller, name).connect(callback)
        callbacks.append(callback)

    class Delivery(QObject):
        @Slot(dict)
        def readiness(self, value):
            emit('readiness', value)

        @Slot(dict)
        def snapshot(self, value):
            emit('snapshot', value)

        @Slot(dict)
        def visual(self, value):
            emit('visual', value)

        @Slot()
        def started(self):
            emit('started', {})

        @Slot(object)
        def finished(self, report):
            nonlocal pending
            QCoreApplication.sendPostedEvents(None, QEvent.MetaCall)
            reports.append(report)
            if pending is None:
                pending = 'automatic_stop'

        @Slot()
        def commands(self):
            nonlocal command_sequence, prepared, pending, completed
            try:
                if outbox.snapshot()['failure'] is not None:
                    raise RuntimeError('Measurement output failed')
                if connection.poll():
                    command = connection.recv()
                    command_sequence = validate(command, command_sequence, COMMANDS)
                    kind = command['kind']
                    if kind == 'prepare' and not prepared:
                        config = config_from_dict(command['config'])
                        if config.test_type != 'Sprint and Gait Test':
                            raise ValueError('Process backend is limited to ground walking')
                        controller.quality_policy = BeamQualityPolicy(**command['quality_policy'])
                        controller.prepare(config)
                        refs['thread'] = controller._thread
                        prepared = True
                        emit('prepared', dict(batch_size=40))
                    elif kind == 'start' and prepared and not controller.is_running:
                        controller.start(acknowledge_quality=command['acknowledge_quality'],
                                         quality_key=command['quality_key'])
                    elif kind in {'stop', 'discard', 'close'} and prepared and pending is None:
                        pending = kind
                        if controller.is_running:
                            if kind == 'discard':
                                raise RuntimeError('Cannot discard a running measurement')
                            controller.stop(command.get('reason', 'manual'))
                        else:
                            controller.discard()
                    elif kind == 'retry_device' and prepared:
                        controller.retry_device()
                    elif kind == 'refresh_led_health' and prepared:
                        controller.refresh_led_health()
                    else:
                        raise ValueError('Unexpected measurement phase: ' + kind)
                if pending and controller._thread is None:
                    if refs['thread'].isRunning():
                        raise RuntimeError('Measurement thread stop unconfirmed')
                    if any(thread.name == 'CyUsbInterfaceReader' for thread in threading.enumerate()):
                        raise RuntimeError('USB reader stop unconfirmed')
                    completed = pending
                    emit('command_completed', dict(kind=pending, reader_stopped=True, qt_thread_stopped=True))
                    timer.stop()
                    app.quit()
            except BaseException as exc:
                errors.append(repr(exc))
                timer.stop()
                app.quit()

    delivery = Delivery()
    controller.walking_readiness_changed.connect(delivery.readiness)
    controller.gait_snapshot.connect(delivery.snapshot)
    controller.footprint_visual_frame.connect(delivery.visual)
    controller.session_started.connect(delivery.started)
    controller.session_finished.connect(delivery.finished)
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(delivery.commands)
    timer.start()
    emit('actor_ready', dict(batch_size=40))
    app.exec()
    timer.stop()
    if controller._thread is not None:
        try:
            controller.stop('error') if controller.is_running else controller.discard()
        except BaseException as exc:
            errors.append('cleanup:' + repr(exc))
    if reports:
        try:
            artifact = save_report(folder, reports[0])
            emit('report', artifact)
        except BaseException as exc:
            errors.append('report:' + repr(exc))
    complete = not errors and completed is not None and controller._thread is None and len(reports) <= 1
    emit('terminal', dict(complete=complete, errors=errors, report_expected=bool(reports)))
    writer_finished = outbox.finish(5)
    outbox.preserve(folder / 'output_snapshot')
    result = dict(complete=complete and writer_finished, errors=errors, completed_control=completed,
                  report_saved=(folder / 'report.json').exists(), output=outbox.snapshot())
    (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    connection.close()
    if not result['complete']:
        raise SystemExit(1)
