"""Real-time, hardware-free acceptance through SessionController and formal Qt views.

Run: QT_API=pyside6 python -m tools.replay_ground_ui CAPTURE.csv \
    --accept-degraded --output-dir exports/ground_ui_replay
Use --scenario processing_stall, source_silence or disconnect to inject faults.
The report stays open for review; --auto-exit closes it after saving evidence.
--baseline accepts a JSON produced by tools.replay_ground_session. No SubjectStore,
USB driver, camera preview or network service is started. Close the window to abort.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import threading
import time

from qtpy.QtCore import QObject, QEventLoop, QTimer, Qt, Signal, Slot
from qtpy.QtWidgets import QApplication, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from config.walking_config import WalkingConfig
from tools.validate_ground_observation import load_capture
from ui.session_controller import SessionController
from ui.views.execution_view import ExecutionView
from ui.views.report_view import ReportView

SCENARIOS = ('normal', 'processing_stall', 'source_silence', 'disconnect')
MATCH_FIELDS = ('summary', 'exported_frames', 'exported_contact_sha256', 'export_timestamps_sha256', 'raw_buffer')


def frame_digest_update(digest, frame):
    digest.update(frame.sample_index.to_bytes(8, 'little'))
    digest.update(frame.contact_bits)
    digest.update(frame.valid_bits)


def intervals(times):
    values = sorted((b - a) * 1000 for a, b in zip(times, times[1:]))
    return {'count': len(times), 'p95_ms': values[int((len(values) - 1) * .95)] if values else None,
            'max_ms': values[-1] if values else None}


class ReplayWorker(QObject):
    data_received = Signal(str)
    device_state_changed = Signal(str, str)
    sensor_frame_received = Signal(object)
    acquisition_issue = Signal(object)
    layout_detected = Signal(object)
    stall_requested = Signal()
    exhausted = Signal()
    failed = Signal(str)

    def __init__(self, frames, checked_sample, scenario, **_kwargs):
        super().__init__()
        self.frames, self.checked_sample, self.scenario = frames, checked_sample, scenario
        self.cancel = threading.Event()
        self.armed = threading.Event()
        self.reader = None
        self.sent = 0
        self.last_sent_at = None
        self.sent_digest = hashlib.sha256()
        self.stall_started = self.stall_finished = None
        self.fault_at = None
        self.start_barrier_s = None
        self.poll_after_stall = lambda: None
        self.stall_requested.connect(self.block_processing, Qt.QueuedConnection)

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit('connected', '离线数据源已就绪')

    @Slot()
    def prepare_walking_capture(self):
        self.start_capture()

    @Slot()
    def start_capture(self):
        if self.reader is not None:
            return
        self.layout_detected.emit(self.frames[0].layout)
        self.device_state_changed.emit('streaming', '正在回放历史记录')
        self.reader = threading.Thread(target=self.read_frames, name='offline-usb-reader', daemon=True)
        self.reader.start()

    def read_frames(self):
        try:
            origin = self.frames[0].received_monotonic_ns
            deadline_origin = time.perf_counter()
            armed_recorded_ns = None
            injected = False
            for raw in self.frames:
                target = deadline_origin + (raw.received_monotonic_ns - origin) / 1e9
                if self.cancel.wait(max(0, target - time.perf_counter())):
                    return
                if (armed_recorded_ns is not None and not injected
                        and raw.received_monotonic_ns - armed_recorded_ns >= 500_000_000):
                    injected = True
                    self.fault_at = time.perf_counter()
                    if self.scenario == 'processing_stall':
                        self.stall_requested.emit()
                    elif self.scenario in ('source_silence', 'disconnect'):
                        if self.scenario == 'disconnect':
                            self.device_state_changed.emit('disconnected', '离线注入断连')
                        return
                incoming = replace(raw, received_monotonic_ns=time.perf_counter_ns())
                self.sensor_frame_received.emit(incoming)
                self.last_sent_at = incoming.received_monotonic_ns / 1e9
                frame_digest_update(self.sent_digest, incoming)
                self.sent += 1
                if raw.sample_index == self.checked_sample:
                    barrier = time.perf_counter()
                    while not self.armed.wait(.01):
                        if self.cancel.is_set():
                            return
                        if time.perf_counter() - barrier > .8:
                            raise RuntimeError('Start acknowledgement did not arrive within 800 ms')
                    self.start_barrier_s = time.perf_counter() - barrier
                    deadline_origin += self.start_barrier_s
                    armed_recorded_ns = raw.received_monotonic_ns
            self.exhausted.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def block_processing(self):
        self.stall_started = time.perf_counter()
        time.sleep(1.2)  # Deliberately block the measurement QThread, not the reader or UI.
        self.stall_finished = time.perf_counter()
        # Force the overdue watchdog ahead of draining, as in the startup race.
        self.poll_after_stall()

    @Slot()
    def stop(self):
        self.cancel.set()
        self.armed.set()
        if self.reader is not None:
            self.reader.join(2)


class ReplayWindow(QWidget):
    closing = Signal()

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)


class GroundUiReplay(QObject):
    def __init__(self, frames, baseline, scenario, output_dir, accept_degraded):
        super().__init__()
        self.frames, self.baseline, self.scenario = frames, baseline, scenario
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.accept_degraded = accept_degraded
        self.loop = QEventLoop()
        self.result = None
        self.processed = 0
        self.processed_digest = hashlib.sha256()
        self.max_queue = 0
        self.pending_at_eof = None
        self.recovered_at = None
        self.heartbeat_times, self.snapshot_times = [], []
        self.measurement_thread_verified = False
        self.checked_sample_index = None
        self.eof = False
        self.execution_saved = False
        self.finishing = False
        self.quality_finished_at = None
        self.started_at = time.perf_counter()
        self.last_progress_at = self.started_at
        self.worker = ReplayWorker(frames, baseline['checked_sample_index'], scenario)
        self.controller = SessionController(worker_factory=lambda **kw: self.worker)
        self.window = ReplayWindow()
        self.window.setWindowTitle('映衡 · 离线验收（不保存受试者记录）')
        self.window.resize(1440, 900)
        self.window.setStyleSheet('background:#0d121a; color:#e0e0e0;')
        layout = QVBoxLayout(self.window)
        self.banner = QLabel(f'离线回放 · {scenario} · 无设备 / 无视频 · 不保存受试者记录')
        self.banner.setStyleSheet('background:#553600; color:#ffdf94; padding:10px; font-size:16px;')
        layout.addWidget(self.banner)
        self.stack = QStackedWidget()
        content = QHBoxLayout()
        layout.addLayout(content, 1)
        content.addWidget(self.stack, 4)
        self.rail = QVBoxLayout()
        content.addLayout(self.rail, 1)
        self.execution = ExecutionView()
        self.report_view = ReportView()
        self.stack.addWidget(self.execution)
        self.stack.addWidget(self.report_view)
        self.rail.addWidget(self.execution._ground_track)
        config = WalkingConfig(stop_type='Software command')
        self.execution.configure(config)
        self.execution._camera_start_timer.stop()
        self.execution._camera_panel.set_vision_enabled(False)
        self.execution._camera_panel.setEnabled(False)
        for button in (self.execution.btn_logi_camera, self.execution.btn_tinyse_camera,
                       self.execution.btn_basic_camera):
            button.setEnabled(False)
        self.execution.set_quality_preflight_required(True)
        c, v = self.controller, self.execution
        c.device_state_changed.connect(v.on_device_state)
        c.device_layout_changed.connect(v.on_device_layout)
        c.walking_readiness_changed.connect(v.on_walking_readiness)
        c.walking_readiness_changed.connect(self.on_readiness)
        c.session_started.connect(v.on_session_started)
        c.session_started.connect(self.on_started)
        c.gait_snapshot.connect(v.on_gait_snapshot)
        c.gait_snapshot.connect(self.on_snapshot)
        c.footprint_visual_frame.connect(v.on_footprint_visual_frame)
        c.beam_quality_notice.connect(v.on_beam_quality_notice)
        c.session_finished.connect(self.on_report)
        v.stop_requested.connect(lambda: c.stop('manual'))
        self.window.closing.connect(self.abort)
        self.worker.exhausted.connect(self.on_eof)
        self.worker.failed.connect(self.fail)
        self.tick = QTimer(self)
        self.tick.setInterval(20)
        self.tick.timeout.connect(self.observe)
        # prepare starts a QThread; main-thread signals cannot start the reader
        # until the event loop returns, leaving time to install observation hooks.
        c.prepare(config)
        self.inbox = c._frame_inbox
        consume = self.inbox._consume

        def observed_consume(items):
            self.measurement_thread_verified = self.inbox.thread().isCurrentThread()
            consume(items)
            for issue, frame in items:
                if not issue:
                    self.processed += 1
                    frame_digest_update(self.processed_digest, frame)
        self.inbox._consume = observed_consume
        self.worker.poll_after_stall = c._quality.poll
        c._quality.finished.connect(self.on_quality_finished, Qt.DirectConnection)
        self.window.show()
        self.tick.start()

    @Slot(dict)
    def on_readiness(self, status):
        if status.get('ready') and not self.controller.is_running:
            if status.get('requires_acknowledgement') and not self.accept_degraded:
                self.fail('Historical capture requires --accept-degraded for offline acknowledgement')
                return
            self.controller.start(acknowledge_quality=self.accept_degraded, quality_key=status['device_key'])

    @Slot()
    def on_started(self):
        self.checked_sample_index = self.controller._quality.context.checked_sample_index
        self.worker.armed.set()

    @Slot(dict)
    def on_snapshot(self, _snapshot):
        self.snapshot_times.append(time.perf_counter())

    @Slot(str)
    def on_quality_finished(self, _reason):
        self.quality_finished_at = time.perf_counter()

    @Slot()
    def on_eof(self):
        self.eof = True
        self.pending_at_eof = len(self.inbox._pending)

    @Slot()
    def observe(self):
        now = time.perf_counter()
        self.heartbeat_times.append(now)
        with self.inbox._lock:
            pending = len(self.inbox._pending)
        self.max_queue = max(self.max_queue, pending)
        if now - self.last_progress_at >= 30:
            print(f'{self.scenario}: {self.worker.sent}/{len(self.frames)} received, '
                  f'{self.processed} processed, {pending} queued', flush=True)
            self.last_progress_at = now
        if self.worker.stall_finished and self.recovered_at is None and pending == 0:
            self.recovered_at = now
        if self.controller.is_running and not self.execution_saved:
            if self.worker.sent >= min(len(self.frames) - 1, self.baseline['checked_sample_index'] + 6000):
                self.save_screen('execution.png')
                self.execution_saved = True
        if self.eof and pending == 0 and self.processed == self.worker.sent:
            self.controller.stop('manual')
        duration = (self.frames[-1].received_monotonic_ns - self.frames[0].received_monotonic_ns) / 1e9
        if now - self.started_at > duration + 20:
            self.fail('Replay exceeded recording duration plus 20 seconds')

    def save_screen(self, name):
        if not self.window.grab().save(str(self.output_dir / name)):
            raise RuntimeError('Failed to save screenshot')

    @Slot(object)
    def on_report(self, report):
        self.finishing = True
        self.tick.stop()
        self.save_screen('execution-final.png')
        digest = hashlib.sha256()
        for bits in report.export_frames:
            digest.update(bytes(bits))
        self.result = {
            'scenario': self.scenario, 'finish_reason': report.finish_reason,
            'clock': 'real_host_clock_recorded_arrival_pacing',
            'checked_sample_index': self.checked_sample_index,
            'startup_barrier_s': self.worker.start_barrier_s,
            'input_frames': len(self.frames), 'sent_frames': self.worker.sent,
            'processed_frames': self.processed,
            'sent_digest': self.worker.sent_digest.hexdigest(),
            'processed_digest': self.processed_digest.hexdigest(),
            'measurement_qthread_verified': self.measurement_thread_verified,
            'reader_stopped': not self.worker.reader.is_alive(),
            'max_pending_frames': self.max_queue, 'pending_at_eof': self.pending_at_eof,
            'queue_observation_interval_ms': self.tick.interval(),
            'pending_after_stop': len(self.inbox._pending),
            'ui_heartbeat': intervals(self.heartbeat_times), 'gait_snapshot_intervals': intervals(self.snapshot_times),
            'stall_duration_s': (self.worker.stall_finished - self.worker.stall_started)
                if self.worker.stall_finished else None,
            'recovery_after_stall_s': (self.recovered_at - self.worker.stall_finished)
                if self.recovered_at else None,
            'finish_after_fault_s': (self.quality_finished_at or time.perf_counter()) - self.worker.fault_at
                if self.worker.fault_at else None,
            'finish_after_last_frame_s': (self.quality_finished_at or time.perf_counter()) - self.worker.last_sent_at,
            'wall_seconds': time.perf_counter() - self.started_at,
            'summary': report.walking_summary, 'exported_frames': len(report.export_frames),
            'exported_contact_sha256': digest.hexdigest(),
            'export_timestamps_sha256': hashlib.sha256(json.dumps(report.export_timestamps).encode()).hexdigest(),
            'raw_buffer': report.report_config_snapshot['raw_buffer'],
            'synthetic_sensor_frames': 0,
        }
        checks = {'worker_thread': self.measurement_thread_verified, 'reader_stopped': self.result['reader_stopped'],
                  'preflight_boundary': self.checked_sample_index == self.baseline['checked_sample_index']}
        if self.scenario in ('normal', 'processing_stall'):
            checks.update({key: self.result[key] == self.baseline[key] for key in MATCH_FIELDS})
            checks.update(all_input_processed=self.worker.sent == self.processed == len(self.frames),
                          ordered_data_preserved=self.result['sent_digest'] == self.result['processed_digest'],
                          queue_drained=self.result['pending_after_stop'] == 0,
                          finish_reason=report.finish_reason == 'manual')
            if self.scenario == 'processing_stall':
                checks['stall_recovered'] = self.recovered_at is not None and self.result['stall_duration_s'] >= 1.2
        else:
            checks['finish_reason'] = report.finish_reason == (
                'data_timeout' if self.scenario == 'source_silence' else 'disconnected')
            if self.scenario == 'source_silence':
                checks['timeout_not_premature'] = self.result['finish_after_last_frame_s'] > 1
        self.result['checks'] = checks
        self.result['passed'] = all(checks.values())
        self.report_view.load_report(report)
        self.execution._ground_track.hide()
        self.rail.addWidget(self.report_view._replay_panel)
        self.report_view._replay_panel.show()
        self.stack.setCurrentWidget(self.report_view)
        self.banner.setText(f'离线回放 · {self.scenario} · 已结束：{report.finish_reason} · 不保存受试者记录')
        QTimer.singleShot(200, self.finish)

    @Slot()
    def finish(self):
        self.save_screen('report.png')
        (self.output_dir / 'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')
        self.execution.reset()
        self.loop.quit()

    @Slot(str)
    def fail(self, message):
        if self.finishing:
            return
        self.finishing = True
        self.tick.stop()
        self.worker.cancel.set()
        self.controller.discard() if not self.controller.is_running else self.controller._cleanup()
        self.result = {'passed': False, 'error': message, 'scenario': self.scenario}
        self.finish()

    @Slot()
    def abort(self):
        if not self.finishing:
            self.fail('Window closed before acceptance completed')

    def run(self):
        self.loop.exec()
        return self.result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--scenario', choices=SCENARIOS, default='normal')
    parser.add_argument('--accept-degraded', action='store_true')
    parser.add_argument('--auto-exit', action='store_true', help='Close after writing acceptance results')
    parser.add_argument('--baseline', type=Path, default=Path('exports/offline_replay_20261003/walking.json'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if any((args.output_dir / name).resolve() in {args.capture.resolve(), args.baseline.resolve()}
           for name in ('result.json', 'execution.png', 'execution-final.png', 'report.png')):
        parser.error('Output must not overwrite the capture or baseline')
    source_sha = hashlib.sha256(args.capture.read_bytes()).hexdigest()
    entries = json.loads(args.baseline.read_text(encoding='utf-8'))['captures']
    entry = next((c for c in entries if c['source_sha256'] == source_sha), None)
    if entry is None:
        parser.error('Capture SHA256 missing from baseline; first run tools.replay_ground_session')
    baseline = next(r for r in entry['runs'] if r['scenario'] == 'normal')
    if not baseline['armed']:
        parser.error('Baseline did not arm')
    frames = load_capture(args.capture)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    run = GroundUiReplay(frames, baseline, args.scenario, args.output_dir, args.accept_degraded)
    result = run.run()
    result.update(source=str(args.capture), source_sha256=source_sha,
                  source_unchanged=hashlib.sha256(args.capture.read_bytes()).hexdigest() == source_sha,
                  baseline=str(args.baseline), platform=platform.platform(), qt_platform=app.platformName(), limitations=[
                      'Mac Qt scheduling validation, not Windows hardware or camera validation.',
                      'No video or human labels; step counts and sides are not accuracy ground truth.',
                      'Startup barrier matches baseline preflight boundary; EOF uses software-command stop.',
                      'Long reports retain a bounded raw buffer; complete input is audited separately.'])
    result['passed'] = result['passed'] and result['source_unchanged']
    (args.output_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result.get(k) for k in ('scenario', 'passed', 'finish_reason', 'error', 'checks')}, ensure_ascii=False), flush=True)
    if not args.auto_exit:
        app.setQuitOnLastWindowClosed(True)
        app.exec()
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
