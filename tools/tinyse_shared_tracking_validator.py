"""Record the actual embedded-panel pose/SDK pipeline in an isolated run."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import signal
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--preview-only', action='store_true', help='Set widest view and record without following')
    parser.add_argument('--show', action='store_true', help='Show the same live panel in the interactive desktop')
    args = parser.parse_args(argv)
    if not 1 <= args.duration <= 600:
        parser.error('duration must be in [1, 600] seconds')
    if args.output.exists():
        parser.error('output must be a new directory')
    args.output.mkdir(parents=True)

    import cv2
    from qtpy.QtCore import Qt, QTimer
    from qtpy.QtWidgets import QApplication, QLabel
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    from vision.gimbal_tracking import TrackingSpeeds

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    log = (args.output / 'events.jsonl').open('w', encoding='utf-8')
    state = {'started_at': None, 'finishing': False, 'errors': [],
             'sdk_stop_reply': False, 'recording_started': False}
    phases = ((0, '正面站立'), (10, '转为侧面'), (20, '回正面'),
              (30, '缓慢横向行走'), (45, '加快横向行走'), (60, '短时离开画面，再返回'))
    last_phase = [None]

    def emit(value):
        log.write(json.dumps({'observed_at': time.perf_counter(), **value}) + '\n')
        log.flush()

    class Panel(EmbeddedCameraPanel):
        def _ensure_control(self, apply_settings=True):
            previous = self._control
            result = super()._ensure_control(apply_settings)
            if result and self._control is not previous:
                control = self._control
                control.tracking_event.connect(emit)
                control.failed.connect(error)
                control.completed.connect(completed)
                control.closed.connect(lambda: closed(control))
            return result

        def _start_capture(self):
            if args.preview_only:
                self._disconnect_sdk_tracking()
                self._sdk_tracking = False
                self._auto_tracking = False
            super()._start_capture()

        def _on_error(self, message):
            error(message)
            super()._on_error(message)

        def closeEvent(self, event):
            finish()
            event.accept()  # The application loop remains alive until SDK closed.

    def closed(control):
        state['sdk_stop_reply'] = control._stop_confirmed
        emit({'event': 'sdk_process_closed', 'stop_reply': control._stop_confirmed})

    def error(message):
        state['errors'].append(message)
        emit({'event': 'error', 'message': message})
        finish()

    def completed(method, result):
        emit({'event': 'control_reply', 'method': method, 'result': result})
        if method == 'tracking_stop' and result == 0:
            state['sdk_stop_reply'] = True

    def finish():
        if state['finishing']:
            return
        state['finishing'] = True
        if panel._display_frame is not None:
            cv2.imwrite(str(args.output / 'end.jpg'), panel._display_frame)
        emit({'event': 'finish_requested'})
        panel.shutdown()

    def poll():
        if state['finishing']:
            if panel._closing_control is not None:
                return
            report = {**state, 'ended_at': time.perf_counter(),
                      'stop_unconfirmed': panel._control_stop_failed,
                      'hardware_motion_verified': False}
            (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            log.close()
            timer.stop()
            app.exit(1 if state['errors'] or panel._control_stop_failed else 0)
            return
        if state['started_at'] is None:
            if panel._display_frame is None:
                if time.perf_counter() - launch > 30:
                    error('Preview did not become ready in 30 seconds')
                return
            path = panel._capture.start_record(args.output / 'capture', preserve_raw=True)
            if path is None:
                error('Native recording did not start')
                return
            state['recording_started'] = True
            state['started_at'] = time.perf_counter()
            cv2.imwrite(str(args.output / 'start.jpg'), panel._display_frame)
            emit({'event': 'recording_started', 'path': path})
            print('RECORDING_STARTED', flush=True)
        if time.perf_counter() - state['started_at'] >= args.duration:
            finish()
        elif not args.preview_only:
            elapsed = time.perf_counter() - state['started_at']
            phase = next(text for start, text in reversed(phases) if elapsed >= start)
            if phase != last_phase[0]:
                last_phase[0] = phase
                panel.setWindowTitle(f'Tiny SE 联合验证：{phase}')
                if args.show:
                    phase_label.setText(f'{phase}（第 {int(elapsed) + 1} / {int(args.duration)} 秒）')
                emit({'event': 'requested_phase', 'phase': phase, 'elapsed': elapsed})
                print(f'PHASE {phase}', flush=True)
            elif args.show:
                phase_label.setText(f'{phase}（第 {int(elapsed) + 1} / {int(args.duration)} 秒）')

    panel = Panel()
    panel.set_vision_enabled(True)
    panel._chk_sdk_tracking.setChecked(True)
    if args.show:
        phase_label = QLabel('准备画面，请让头到脚入镜', panel)
        phase_label.setAlignment(Qt.AlignCenter)
        phase_label.setWordWrap(True)
        phase_label.setStyleSheet('font-size: 32px; font-weight: bold; color: white; background: #17324d; padding: 14px;')
        panel.layout().insertWidget(0, phase_label)
        panel.resize(1280, 800)
        panel.setWindowTitle('Tiny SE 联合验证：准备画面')
        panel.show()
    root = Path(__file__).resolve().parents[1]
    emit({'event': 'configuration', 'duration': args.duration,
          'model_sha256': hashlib.sha256((root / 'models/pose_landmarker_full.task').read_bytes()).hexdigest(),
          'preview_only': args.preview_only,
          'input': 'existing embedded panel, unmirrored full image resized to width 640',
          'fov_request': 0, 'zoom_request': 1.0,
          'tracking_speeds': asdict(TrackingSpeeds()),
          'source_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                            for name in ('vision/gimbal_tracking.py', 'tools/tinyse_shared_tracking_validator.py')},
          'manifest': str(root / 'control-manifest.json')})
    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(poll)
    timer.start()
    signal.signal(signal.SIGINT, lambda *_: finish())
    launch = time.perf_counter()
    panel.start_preview()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
