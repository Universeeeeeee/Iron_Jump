"""Replay recorded USB frames through the ground session without opening devices.

Uses a virtual host clock and the real quality gate, ordered inbox, engine and
report builder. This verifies logic, not Windows scheduling or camera alignment.
Run: QT_API=pyside6 python -m tools.replay_ground_session CAPTURE.csv --output replay.json
Add --accept-degraded to simulate accepting bad beams within the quality policy.
"""
import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

from qtpy.QtCore import QCoreApplication, QEvent

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.device_quality_session import DeviceQualitySession
from engine.gait_engine import GaitEngine
from hardware.beam_quality import BeamQualityPolicy
from tools.validate_ground_observation import load_capture
from ui.session_controller import _GroundFrameInbox

SCENARIOS = ('normal', 'processing_stall', 'legacy_processing_stall', 'source_silence', 'disconnect')


def replay_session(frames, scenario='normal', *, mode='walk', accept_degraded=False):
    if not frames:
        raise ValueError('Capture contains no complete frames')
    if scenario not in SCENARIOS:
        raise ValueError(f'Unknown scenario: {scenario}')
    if any(b.received_monotonic_ns < a.received_monotonic_ns for a, b in zip(frames, frames[1:])):
        raise ValueError('Host arrival times must be monotonic; do not reorder the capture')
    config = (WalkingConfig if mode == 'walk' else OvergroundRunningConfig)(stop_type='Software command')
    engine = GaitEngine(config=config)
    gate = DeviceQualitySession(config, BeamQualityPolicy(), engine)
    engine.quality = gate
    inbox = _GroundFrameInbox(gate)
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    ended = []
    gate.finished.connect(ended.append)
    engine.test_finished.connect(ended.append)
    now = [10_000_000_000]
    origin = frames[0].received_monotonic_ns
    armed_at = None
    checked_sample = None
    next_poll = now[0] + 100_000_000
    stalled = False
    recovered = False
    max_queue = received_count = 0
    report = None
    started = time.perf_counter()

    def poll():
        if scenario == 'legacy_processing_stall':
            # Reproduce only the old watchdog predicate, using the same engine.
            latest = gate.latest_received_frame
            gate.latest_received_frame = None
            try:
                gate.poll()
            finally:
                gate.latest_received_frame = latest
        else:
            gate.poll()

    def drain():
        while inbox._pending and not gate.done:
            inbox.drain()

    try:
        with patch('time.perf_counter_ns', side_effect=lambda: now[0]):
            for raw in frames:
                target = 10_000_000_000 + raw.received_monotonic_ns - origin
                stall_start = armed_at + 500_000_000 if armed_at is not None else None
                stall_end = stall_start + 1_200_000_000 if stall_start is not None else None
                # A blocked measurement thread cannot run either timer. On resume,
                # deliberately dispatch its overdue watchdog before the drain.
                while next_poll <= target and not ended:
                    if not (scenario.endswith('processing_stall') and stall_start is not None
                            and stall_start <= next_poll <= stall_end):
                        now[0] = next_poll
                        poll()
                    next_poll += 100_000_000
                if ended:
                    break
                now[0] = target
                if stall_start is not None and target >= stall_start and scenario in {'source_silence', 'disconnect'}:
                    if scenario == 'source_silence':
                        now[0] = gate.latest_received_frame.received_monotonic_ns + 1_000_000_001
                        poll()
                    else:
                        gate.on_device_state('disconnected', 'Offline injected disconnect')
                    break
                incoming = replace(raw, received_monotonic_ns=target)
                inbox.on_frame(incoming)
                received_count += 1
                max_queue = max(max_queue, len(inbox._pending))
                if (scenario.endswith('processing_stall') and stall_start is not None
                        and stall_start <= target < stall_end):
                    stalled = True
                    continue
                if stalled and not recovered:
                    poll()
                    recovered = True
                    if ended:
                        break
                drain()
                if gate.context is None and gate.preflight.context is not None:
                    gate.arm_checked((gate.preflight.context.key, accept_degraded))
                    if gate.context is not None:
                        armed_at = target
                        checked_sample = gate.context.checked_sample_index
                if ended:
                    break
            pending_at_stop = len(inbox._pending)
            inbox.finish()
            status = gate._status() if gate.context is None else None
            gate.halt()
            engine.overground.halt()
            reason = ended[0] if ended else 'manual'
            if gate.context is not None:
                report = engine.build_report(reason)
            context = gate.context
    finally:
        inbox._timer.stop()
        gate.halt()
        engine.overground.halt()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(engine, QEvent.DeferredDelete)

    result = {
        'scenario': scenario, 'mode': mode, 'clock': 'virtual_host_arrival',
        'armed': armed_at is not None, 'checked_sample_index': checked_sample,
        'finish_reason': reason if report else 'not_armed',
        'finish_trigger': ended[0] if ended else 'end_of_recording',
        'received_frames': received_count, 'pending_at_stop': pending_at_stop,
        'max_pending_frames': max_queue, 'injected_processing_stall': stalled,
        'resumed_after_stall': recovered, 'processing_seconds': time.perf_counter() - started,
        'synthetic_sensor_frames': 0,
    }
    if report is None:
        result['readiness'] = {k: status.get(k) for k in ('ready', 'message', 'bad_indices')}
        return result
    summary = report.walking_summary if mode == 'walk' else report.running_summary
    digest = hashlib.sha256()
    for bits in report.export_frames:
        digest.update(bytes(bits))
    result.update(
        masked_indices=list(context.bad_indices), summary=summary,
        exported_frames=len(report.export_frames), exported_contact_sha256=digest.hexdigest(),
        export_timestamps_sha256=hashlib.sha256(json.dumps(report.export_timestamps).encode()).hexdigest(),
        raw_buffer=report.report_config_snapshot['raw_buffer'],
        quality_events=report.report_config_snapshot['beam_quality']['events'],
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', nargs='+', type=Path)
    parser.add_argument('--mode', choices=('walk', 'run'), default='walk')
    parser.add_argument('--scenarios', nargs='+', choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument('--accept-degraded', action='store_true', help='Simulate acknowledgement of permitted bad beams')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {path.resolve() for path in args.captures}:
        parser.error('Output must not overwrite an input capture')
    app = QCoreApplication.instance() or QCoreApplication([])
    output = {
        'limitations': ['Virtual-clock logic replay; no hardware or OS timing validation.',
                       'No video or human foot labels: step/side outputs are not accuracy ground truth.',
                       'Software-command stop; EOF does not invent a final foot lift or normal exit.'],
        'captures': [],
    }
    for path in args.captures:
        frames = load_capture(path)
        entry = {'path': str(path), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                 'frames': len(frames), 'segments': len(frames[0].layout.segments) if frames else None,
                 'sample_span_s': frames[-1].sample_time_s - frames[0].sample_time_s if frames else None,
                 'quality_flags': dict(Counter(flag for frame in frames for flag in frame.quality_flags)),
                 'missing_samples': sum(frame.dropped_frames_before for frame in frames), 'runs': []}
        output['captures'].append(entry)
        for scenario in args.scenarios:
            run = replay_session(frames, scenario, mode=args.mode, accept_degraded=args.accept_degraded)
            entry['runs'].append(run)
            print(f"{path.name}: {scenario}: {run['finish_reason']}, "
                  f"{run.get('exported_frames', 0)} exported, "
                  f"{run.get('summary', {}).get('valid_steps')} steps", flush=True)
        normal = next((r for r in entry['runs'] if r['scenario'] == 'normal'), None)
        stalled = next((r for r in entry['runs'] if r['scenario'] == 'processing_stall'), None)
        if normal and stalled and normal['armed'] and stalled['resumed_after_stall']:
            entry['stall_preserves_results'] = all(normal[k] == stalled[k] for k in
                ('summary', 'exported_frames', 'exported_contact_sha256', 'export_timestamps_sha256'))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(c.get('stall_preserves_results') is False for c in output['captures']))


if __name__ == '__main__':
    raise SystemExit(main())
