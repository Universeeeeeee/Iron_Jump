"""Deterministic walking/grid pairing fault injection; no hardware or model access.

Uses real LiveWalkingVision, clock synchronizers, event scheduler, identity and
landing classifier. Camera poses and grid snapshots are synthetic, independently
timed inputs, not human accuracy evidence. Service thread scheduling is excluded.
"""
import argparse
from dataclasses import asdict, replace
import html
import json
from pathlib import Path
from types import SimpleNamespace

from vision.event_scheduler import EventWindowScheduler
from vision.foot_reference import FootPoseSample, Landmark
from vision.live_walking import LiveWalkingVision
from vision.service import EventHook, PoseInferenceRecord


CASES = {
    'left': 'left', 'right': 'right', 'one_frame_dropped': 'left',
    'pending_touch_order': 'left',
    'two_frames_dropped': 'unknown', 'person_missing': 'unknown',
    'legs_overlap': 'unknown', 'labels_swapped': 'unknown',
    'low_quality': 'unknown', 'both_feet': 'unknown', 'stationary': 'unknown',
    'camera_stopped': 'unknown', 'callback_jitter': 'unknown',
    'clock_reset': 'unknown', 'late_contact': 'unknown', 'slow_inference': 'unknown',
    'stream_reset': 'unknown', 'excluded_pending': 'unknown', 'excluded_decided': 'unknown',
}


def pose_at(ms, case):
    if case == 'person_missing' and ms in (1950, 2000):
        return None
    values = {}
    for side, x in (('left', .35), ('right', .65)):
        moving = side == ('right' if case == 'right' else 'left') or case == 'both_feet'
        y = .82
        if moving and case != 'stationary':
            y = .58 if ms <= 1850 else min(.83, .58 + (ms - 1850) / 150 * .25)
        for joint, height in (('hip', .30), ('knee', .55), ('ankle', y), ('heel', y), ('foot_index', y)):
            values[f'{side}_{joint}'] = Landmark(x, height, 0, .99, .99)
    if ms >= 1950:
        original = dict(values)
        for key, point in original.items():
            side, joint = key.split('_', 1)
            if case == 'legs_overlap':
                values[key] = replace(point, x=.5 if side == 'left' else .51)
            elif case == 'labels_swapped':
                values[key] = original[f"{'right' if side == 'left' else 'left'}_{joint}"]
            elif case == 'low_quality':
                values[key] = replace(point, visibility=.2, presence=.2)
    return FootPoseSample(ms / 1000, **values)


class ReplayService:
    """Synchronous transport with the real scheduler; retain exact inferred frames."""
    def __init__(self, config, *, classifier, clock):
        self.pose_inference_ready = EventHook()
        self.status_changed = EventHook()
        self.decision_ready = EventHook()
        self.scheduler = EventWindowScheduler(config)
        self.classifier, self.clock = classifier, clock
        self.frames, self.events, self.decisions, self.inferences = [], [], [], []

    def start(self):
        self.status_changed.emit('ready')

    def stop(self):
        pass

    def submit_frame(self, frame, timestamp, *, metadata=None):
        self.frames.append({'camera_frame_index': frame['index'], 'sample_time_s': frame['ms'] / 1000,
                            'aligned_time_s': timestamp, 'metadata': asdict(metadata) if metadata else None})
        self.scheduler.add_frame((frame, metadata), timestamp)

    def submit_touch_event(self, event_id, timestamp):
        self.events.append({'event_id': event_id, 'event_time_s': timestamp, 'submitted_at_s': self.clock()})
        self.scheduler.add_event(event_id, timestamp, submitted_at_s=self.clock())

    def tick(self):
        def infer(frame, timestamp_ms):
            frame, metadata = frame
            pose = frame['pose']
            if pose is not None:
                pose = replace(pose, timestamp_s=timestamp_ms / 1000)
            self.inferences.append({'camera_frame_index': frame['index'], 'sample_time_s': frame['ms'] / 1000,
                                    'aligned_time_s': timestamp_ms / 1000, 'pose_available': pose is not None,
                                    'metadata': asdict(metadata) if metadata else None})
            self.pose_inference_ready.emit(PoseInferenceRecord(timestamp_ms / 1000, self.clock(), self.clock(), pose,
                                                             frame_metadata=metadata))
            return pose
        while True:
            decisions = self.scheduler.process_ready(infer, self.classifier, now_s=self.clock(), decision_clock=self.clock)
            for decision in decisions:
                self.decisions.append(asdict(decision))
                self.decision_ready.emit(decision)
            if not decisions:
                break


def run_case(case):
    now = [100.0]
    def factory(config, _path, **kwargs):
        return ReplayService(config, classifier=kwargs['classifier'], clock=lambda: now[0])
    vision = LiveWalkingVision(service_factory=factory, clock=lambda: now[0])
    vision.start()
    service = vision._service
    transitions, previous = [], None
    for ms in range(0, 2851, 50):
        jitter = .045 if case == 'callback_jitter' and (ms // 50) % 2 else 0
        now[0] = 100 + ms / 1000 + jitter
        dropped = ((case == 'one_frame_dropped' and ms == 1950)
                   or (case == 'two_frames_dropped' and ms in (1950, 2000))
                   or (case == 'camera_stopped' and ms > 2000))
        if not dropped:
            index = ms // 50
            if case == 'clock_reset' and ms >= 1900:
                index -= 38
            vision.submit_camera_frame({'index': index, 'ms': ms, 'pose': pose_at(ms, case)},
                SimpleNamespace(sample_time_s=ms / 1000, callback_time_s=now[0], frame_index=index))
        # Include a half-tick state change before the pending event is decided.
        special = ms == 2150 and case in {'stream_reset', 'excluded_pending'}
        if ms % 100 == 0 or special:
            contacts = []
            if ms >= (2600 if case == 'late_contact' else 2100):
                excluded = (case == 'excluded_pending' and ms >= 2150 or
                            case == 'excluded_decided' and ms >= 2200)
                exclusion = 'incomplete_contact' if ms < 2800 else ''
                if case == 'pending_touch_order' and ms < 2200:
                    exclusion = 'pending_touch_order'
                contacts = [dict(id=0, start=0.0, side='right', confirmed=True,
                                 label='A', end=None if ms < 2800 else .8,
                                 exclusion='ambiguous_contacts' if excluded else exclusion)]
            snapshot = {'device_timing': {
                'stream_id': 'new' if case == 'stream_reset' and ms >= 2150 else 'grid',
                'sample_time_s': ms / 1000, 'received_time_s': 100 + ms / 1000,
                'frame_index': ms, 'origin_sample_time_s': 2.0}, 'walking': {'contacts': contacts}}
            vision.submit_walking_snapshot(snapshot)
        # Delay processing beyond the 450 ms event deadline while retaining the
        # original camera callback/device times. No wall-clock sleeping is used.
        if case != 'slow_inference' or not 2050 <= ms < 2550:
            service.tick()
        check = vision.display_state()[2]
        if check != previous:
            transitions.append({'host_time_s': now[0], 'check': check})
            previous = check
    final = vision.display_state()[2]
    events = []
    for event in service.events:
        decision = next((d for d in service.decisions if d['event_id'] == event['event_id']), None)
        frames = [frame for frame in service.inferences
                  if event['event_time_s'] - .150 - 1e-6 <= frame['aligned_time_s'] <= event['event_time_s'] + .150 + 1e-6]
        events.append({**event, 'optical_contact_id': 0, 'optical_touch_sample': 2000,
                       'frame_window': frames, 'decision': decision})
    # Known synthetic offset is 100 s; never derive this expectation from the
    # same synchronizer being tested. UI delivery at 2.1 s must not move touch.
    mapping_ok = (all(abs(e['event_time_s'] - 102.0) < 1e-8 for e in service.events)
                  if service.events else None)
    passed = (final is not None and final['label'] == CASES[case]
              and final['reason'] != 'pending' and mapping_ok is not False)
    result = {'case': case, 'expected_label': CASES[case], 'passed': passed,
              'event_mapping_matches_known_clock': mapping_ok, 'final_check': final,
              'grid_clock': asdict(vision._grid_clock.snapshot),
              'camera_clock': asdict(vision._camera_clock.snapshot),
              'events': events, 'display_transitions': transitions}
    vision.stop()
    return result


def write_review(path, results):
    rows, details = [], []
    for r in results:
        check = r['final_check'] or {}
        rows.append('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in
            (r['case'], r['expected_label'], check.get('label'), check.get('reason'), r['passed'])) + '</tr>')
        for event in r['events']:
            decision = event['decision'] or {}
            frame_rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(frame[k]))}</td>' for k in
                ('camera_frame_index', 'sample_time_s', 'aligned_time_s', 'pose_available')) + '</tr>'
                for frame in event['frame_window'])
            details.append(f"<details><summary>{html.escape(r['case'])} · 事件 {event['event_id']}</summary>"
                f"<p>光栅采样 {event['optical_touch_sample']} → 主机落脚时间 {event['event_time_s']:.3f} s；"
                f"提交时间 {event['submitted_at_s']:.3f} s。</p>"
                f"<p>窗口分类：{html.escape(str(decision.get('label')))} / {html.escape(str(decision.get('reason')))}；"
                f"界面最终采用：{html.escape(str(check.get('label')))} / {html.escape(str(check.get('reason')))}。</p>"
                '<table><tr><th>相机帧号</th><th>相机采样时间</th><th>对齐后主机时间</th><th>人体姿态可用</th></tr>'
                + frame_rows + '</table></details>')
    path.write_text('<!doctype html><meta charset="utf-8"><title>左右脚配对离线验收</title>'
        '<style>body{font:16px sans-serif;margin:32px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:8px}</style>'
        '<h1>左右脚配对离线验收</h1><p>使用合成姿态和光栅快照，运行正式时钟同步、事件窗口、腿身份检查和落脚分类。'
        '不运行 MediaPipe 模型、不连接设备；通过数不是人体识别准确率。</p>'
        '<p><a href="pairing.json">逐事件明细：落脚时间、关联帧、判定原因与界面状态变化</a></p>'
        '<table><tr><th>注入场景</th><th>预期</th><th>最终侧别</th><th>原因</th><th>通过</th></tr>' + ''.join(rows) + '</table>'
        '<h2>逐事件关联帧</h2>' + ''.join(details) +
        '<p>事件窗口为落脚前后各 150 ms，决策期限为落脚后 450 ms。单次丢帧可保留判定；姿态间隔超过 100 ms 时保留未知。'
        '左右脚证据不会改写光栅标签。固定相机传输延迟无法仅凭回调时钟消除，仍需同步录像验证物理对齐。</p>', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    results = [run_case(case) for case in CASES]
    output = {'input_kind': 'synthetic_poses_and_grid_snapshots', 'results': results,
              'passed': all(r['passed'] for r in results),
              'limitations': ['No MediaPipe inference or physical camera/grid validation.',
                              'No service-thread or OS scheduling measurement.',
                              'No human accuracy ground truth or fixed camera transport latency calibration.']}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'pairing.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    write_review(args.output_dir / 'review.html', results)
    print(json.dumps({'passed': output['passed'], 'cases': len(results),
                      'failed': [r['case'] for r in results if not r['passed']]}, ensure_ascii=False))
    return 0 if output['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
