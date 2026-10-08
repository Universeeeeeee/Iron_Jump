"""Independent Tiny SE pulse / MediaPipe two-axis tracking experiment.

Run from the branch checkout: python -m tools.tinyse_gimbal_validator --mode pulse
"""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import threading
import time

from camera.gimbal_control import GimbalSdk, SpeedWatchdog
from vision.gimbal_tracking import TrackingSpeeds, lower_body_target, tracking_velocity


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('pulse', 'track'), default='pulse')
    p.add_argument('--duration', type=float, default=60, help='tracking duration in seconds')
    p.add_argument('--pan-gain', type=float, default=240)
    p.add_argument('--pitch-gain', type=float, default=80)
    p.add_argument('--pan-max', type=float, default=90)
    p.add_argument('--pitch-max', type=float, default=30)
    p.add_argument('--pan-sign', type=int, choices=(-1, 1), default=1)
    p.add_argument('--pitch-sign', type=int, choices=(-1, 1), default=-1)
    p.add_argument('--pulse-pan', type=float, default=60, help='higher pan speed; comparison uses half this speed')
    p.add_argument('--no-preview', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--model', type=Path, default=Path(__file__).resolve().parents[1] / 'models/pose_landmarker_full.task')
    return p


class LatestFrame:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None

    def receive(self, jpeg, index, sample_time, callback_time):
        with self.lock:
            self.value = jpeg, index, sample_time, callback_time

    def get(self):
        with self.lock:
            return self.value


def pulse_test(control, frames, emit, output, pan):
    # Equal duration in both directions limits net displacement; feedback and
    # snapshots are retained because SDK success alone does not prove movement.
    pulses = [('pan_low_positive', 0, pan / 2), ('pan_low_negative', 0, -pan / 2),
              ('pan_high_positive', 0, pan), ('pan_high_negative', 0, -pan),
              ('pitch_positive', 15, 0), ('pitch_negative', -15, 0)]
    for label, pitch, speed in pulses:
        control.stop_motion()
        before = control.angles()
        frame = frames.get()
        if frame is not None:
            (output / f'{label}_before.jpg').write_bytes(frame[0])
        started = time.perf_counter()
        while time.perf_counter() - started < .30:
            control.update(pitch, speed, time.perf_counter())
            time.sleep(.02)
        control.stop_motion()
        ended = time.perf_counter()
        time.sleep(.25)
        after = control.angles()
        frame = frames.get()
        if frame is not None:
            (output / f'{label}_after.jpg').write_bytes(frame[0])
        emit({'event': 'pulse', 'label': label, 'pitch': pitch, 'pan': speed,
              'elapsed_s': ended - started, 'before': before, 'after': after})


def track_test(control, frames, adapter, settings, args, emit):
    import cv2
    import numpy as np

    previous_index = -1
    previous_timestamp = -1
    started = time.perf_counter()
    next_inference = started
    while time.perf_counter() - started < args.duration:
        if control.error is not None:
            raise RuntimeError('SDK control failed') from control.error
        now = time.perf_counter()
        item = frames.get()
        if item is None or item[1] == previous_index or now < next_inference:
            time.sleep(.005)
            continue
        jpeg, index, sample_time, captured_at = item
        previous_index = index
        if not 0 <= now - captured_at <= .25:
            control.stop_motion()
            continue
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            control.stop_motion()
            continue
        timestamp = int(captured_at * 1000)
        if timestamp <= previous_timestamp:
            continue
        previous_timestamp = timestamp
        pose = adapter.infer_bgr(image, timestamp)
        target = lower_body_target(pose)
        pitch, pan = tracking_velocity(target, settings)
        # Keep the original frame time: a slow inference must expire, not
        # become a fresh movement command just because it finished now.
        age = time.perf_counter() - captured_at
        if age > .25:
            pitch = pan = 0.0
        control.update(pitch, pan, captured_at)
        emit({'event': 'tracking', 'frame': index, 'sample_time_s': sample_time,
              'frame_age_s': age, 'target': target, 'pitch': pitch, 'pan': pan})
        next_inference = time.perf_counter() + .05
        if not args.no_preview:
            h, w = image.shape[:2]
            cv2.rectangle(image, (int(w * .44), int(h * .44)), (int(w * .56), int(h * .56)), (0, 255, 255), 2)
            if target is not None:
                cv2.circle(image, (int(target[0] * w), int(target[1] * h)), 10, (0, 255, 0), 2)
            cv2.putText(image, f'pan={pan:.1f} pitch={pitch:.1f} | Q/ESC stop', (20, 40), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 255, 255), 2)
            cv2.imshow('Tiny SE MediaPipe gimbal validation', cv2.resize(image, (960, 540)))
            if cv2.waitKey(1) & 0xff in (27, ord('q')):
                break


def main(argv=None):
    args = parser().parse_args(argv)
    settings = TrackingSpeeds(args.pan_gain, args.pitch_gain, args.pan_max,
                              args.pitch_max, args.pan_sign, args.pitch_sign)
    if not 0 < args.duration <= 600 or not 0 < args.pulse_pan <= 180:
        raise ValueError('duration must be in (0, 600], pulse-pan in (0, 180]')
    from camera.tinyse_dshow_capture import TinySeDShowCapture

    output = args.output or Path('exports') / ('tinyse_gimbal_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    output.mkdir(parents=True, exist_ok=False)
    frames = LatestFrame()
    control = capture = adapter = None
    recording = False
    report = {'mode': args.mode, 'settings': asdict(settings),
              'status': 'incomplete', 'hardware_motion_verified': False}
    with (output / 'commands.jsonl').open('w', encoding='utf-8') as log:
        def emit(value):
            value['host_time_s'] = time.perf_counter()
            log.write(json.dumps(value) + '\n')
            log.flush()
            if value['event'] != 'tracking':
                print(json.dumps(value), flush=True)

        try:
            if args.mode == 'track':
                from vision.mediapipe_pose import MediaPipePoseAdapter
                adapter = MediaPipePoseAdapter(args.model)
                adapter.open()
            sdk = GimbalSdk()
            control = SpeedWatchdog(sdk)
            control.start()
            capture = TinySeDShowCapture(on_timed_frame=frames.receive)
            capture.start()
            deadline = time.perf_counter() + 10
            while frames.get() is None and time.perf_counter() < deadline:
                time.sleep(.05)
            if frames.get() is None:
                raise RuntimeError('No camera frames; close other camera previews and retry')
            capture.start_record(output / 'capture')
            recording = True
            initial = capture.stats()
            started = time.perf_counter()
            emit({'event': 'start', 'settings': asdict(settings), 'angles': control.angles()})
            if args.mode == 'pulse':
                pulse_test(control, frames, emit, output, args.pulse_pan)
            else:
                track_test(control, frames, adapter, settings, args, emit)
            control.stop_motion()
            stats = capture.stats()
            report.update(status='commands_completed_hardware_review_required',
                          elapsed_s=time.perf_counter() - started,
                          frames=stats.frames - initial.frames,
                          sample_fps=stats.sample_fps, wall_fps=stats.wall_fps,
                          final_angles=control.angles())
        except (Exception, KeyboardInterrupt) as exc:
            report['error'] = repr(exc)
            raise
        finally:
            # Stop first, before recording flush/model teardown can block.
            try:
                if control is not None:
                    control.close()
                report['stop_command_sent'] = control is not None
            except Exception as exc:
                report.update(status='stop_failed', stop_error=repr(exc))
            try:
                if capture is not None:
                    try:
                        if recording:
                            recorded = capture.stop_record()
                            report['recording'] = {
                                'frames_written': recorded.frames_written,
                                'frames_dropped': recorded.frames_dropped,
                                'last_hresult': recorded.last_hresult,
                            }
                    finally:
                        capture.close()
                if adapter is not None:
                    adapter.close()
                if args.mode == 'track' and not args.no_preview:
                    import cv2
                    cv2.destroyAllWindows()
            except Exception as exc:
                report.update(status='cleanup_failed', cleanup_error=repr(exc))
                raise
            finally:
                (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(f'Results: {output.resolve()}', flush=True)
    return 0 if report['status'] == 'commands_completed_hardware_review_required' else 1


if __name__ == '__main__':
    raise SystemExit(main())
