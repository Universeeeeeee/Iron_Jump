"""Offline video -> production walking pose/classifier -> reviewable evidence.

python -m tools.replay_walking_video VIDEO --output-dir exports/video_review
Optionally supply --annotations manual.json, bound to the source video's SHA256.
This tool never opens cameras or USB and cannot establish grid/video clock sync.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time

from vision.event_scheduler import EventWindowScheduler
from vision.foot_reference import VisionConfig
from vision.leg_identity import LegIdentityAnalyzer
from vision.live_walking import _PreviewAdapter, classify_walking_contact
from vision.pose_overlay import draw_pose_overlay
from vision.session import pose_sample_to_record


def load_manual_events(path, video_sha256):
    if path is None:
        return [], ''
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('video_sha256') != video_sha256:
        raise ValueError('Annotations belong to a different video (SHA256 mismatch)')
    if data.get('timebase') != 'zero_based_video_frame_index':
        raise ValueError('Annotations must use zero_based_video_frame_index')
    events = data['events']
    seen = set()
    for event in events:
        if type(event.get('event_id')) is not int or event['event_id'] < 1 or event['event_id'] in seen:
            raise ValueError('Event IDs must be unique positive integers')
        seen.add(event['event_id'])
        if type(event.get('frame_index')) is not int or event['frame_index'] < 0:
            raise ValueError('Frame indices must be nonnegative integers')
        if event.get('ground_truth', '') not in ('', 'left', 'right', 'skip'):
            raise ValueError('Ground truth must be left, right, skip or empty')
        if event.get('ground_truth') in ('left', 'right') and not str(data.get('reviewer', '')).strip():
            raise ValueError('Human ground truth requires a named reviewer')
    return events, data.get('reviewer', '')


def score_events(rows):
    labelled = [r for r in rows if r['ground_truth'] in ('left', 'right')]
    correct = [r for r in labelled if r['prediction'] == r['ground_truth']]
    wrong = [r for r in labelled if r['prediction'] in ('left', 'right') and r not in correct]
    unknown = [r for r in labelled if r['prediction'] == 'unknown']
    accepted = len(correct) + len(wrong)
    return {'annotated_events': len(labelled), 'unscored_events': len(rows) - len(labelled),
            'correct': len(correct), 'wrong': len(wrong), 'unknown': len(unknown),
            'accuracy': len(correct) / len(labelled) if labelled else None,
            'accepted_accuracy': len(correct) / accepted if accepted else None,
            'coverage': accepted / len(labelled) if labelled else None,
            'wrong_event_ids': [r['event_id'] for r in wrong],
            'high_confidence_wrong_ids': [r['event_id'] for r in wrong if r['confidence'] >= .9]}


def replay_video(video, output_dir, *, annotations=None, model=None, adapter_factory=_PreviewAdapter):
    import cv2

    video, output_dir = Path(video).resolve(), Path(output_dir).resolve()
    names = ('overlay.mp4', 'pose_frames.jsonl', 'frames.jsonl', 'events.json', 'summary.json', 'manual_template.json')
    inputs = {video, Path(annotations).resolve() if annotations else None}
    if any(output_dir / name in inputs for name in names):
        raise ValueError('Output must not overwrite video or manual annotations')
    source_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    events, reviewer = load_manual_events(annotations, source_sha)
    by_frame = {}
    for event in events:
        by_frame.setdefault(event['frame_index'], []).append(event)
    config = VisionConfig(pre_event_ms=150, post_event_ms=150, inference_interval_ms=50,
                          decision_timeout_ms=450, max_frames=20, frame_buffer_ms=1000)
    scheduler = EventWindowScheduler(config)
    identity = LegIdentityAnalyzer()
    model = Path(model or Path(__file__).resolve().parents[1] / 'models/pose_landmarker_full.task')
    adapter = adapter_factory(model)
    capture = cv2.VideoCapture(str(video))
    writer = None
    rows, event_times = [], {}
    count = inferred = poses = 0
    states = Counter()
    latest_pose = None
    latest_identity = None
    previous_time = None
    pts_origin = None
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    # A prior successful summary must not survive a failed rerun as current evidence.
    summary_path = output_dir / 'summary.json'
    summary_path.write_text(json.dumps({'status': 'processing', 'video_sha256': source_sha}))
    try:
        if not capture.isOpened():
            raise ValueError('Could not open video file')
        fps = capture.get(cv2.CAP_PROP_FPS)
        declared_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError('Video has no usable FPS for the review render')
        adapter.open()
        with (output_dir / 'pose_frames.jsonl').open('w', encoding='utf-8') as pose_file, \
             (output_dir / 'frames.jsonl').open('w', encoding='utf-8') as frame_file:
            def infer(frame, timestamp_ms):
                nonlocal latest_pose, latest_identity, inferred, poses
                start = time.perf_counter()
                latest_pose = adapter.infer_bgr(frame, timestamp_ms)
                end = time.perf_counter()
                latest_identity = identity.update(latest_pose)
                inferred += 1
                poses += latest_pose is not None
                record = pose_sample_to_record(latest_pose, frame_index=count,
                    camera_sample_timestamp=None, perf_counter_timestamp=timestamp_ms / 1000,
                    inference_start_timestamp=start, inference_end_timestamp=end)
                # The shared serialization field is a video timeline here, NOT a host/grid clock.
                record['clock_domain'] = 'video_pts'
                record['identity'] = asdict(latest_identity)
                pose_file.write(json.dumps(record) + '\n')
                return latest_pose

            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if not math.isfinite(pts) or pts < 0:
                    raise ValueError('Decoder did not provide a valid video timestamp')
                if pts_origin is None:
                    pts_origin = pts
                timestamp = pts - pts_origin
                if previous_time is not None and timestamp <= previous_time:
                    raise ValueError('Video timestamps are not increasing; cannot silently invent timing')
                previous_time = timestamp
                height, width = frame.shape[:2]
                if writer is None:
                    writer = cv2.VideoWriter(str(output_dir / 'overlay.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
                    if not writer.isOpened():
                        raise RuntimeError('Could not create review video')
                scheduler.add_frame(frame, timestamp)
                for event in by_frame.get(count, []):
                    event_times[event['event_id']] = timestamp
                    scheduler.add_event(event['event_id'], timestamp, submitted_at_s=timestamp)
                while True:
                    decisions = scheduler.process_ready(infer, classify_walking_contact, now_s=timestamp)
                    rows.extend(decision_row(d, events, event_times) for d in decisions)
                    if not decisions:
                        break
                visible = latest_pose if latest_pose is not None and 0 <= timestamp - latest_pose.timestamp_s <= .25 else None
                state = latest_identity.state.value if visible is not None else 'unavailable'
                reason = latest_identity.reason if visible is not None else 'pose_missing_or_stale'
                states[state] += 1
                draw_pose_overlay(frame, visible)
                texts = [f'OFFLINE / NO GRID | frame {count} | {timestamp:.3f}s', f'{state}: {reason}']
                text_width = max(cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .55, 1)[0][0] for text in texts)
                scale = .55 * min(1, (width - 16) / text_width)
                cv2.rectangle(frame, (0, 0), (width, min(height, 56)), (20, 20, 20), -1)
                for line, text in enumerate(texts):
                    cv2.putText(frame, text, (8, 22 + line * 24), cv2.FONT_HERSHEY_SIMPLEX,
                                scale, (255, 255, 255), 1, cv2.LINE_AA)
                writer.write(frame)
                frame_file.write(json.dumps({'frame_index': count, 'video_time_s': timestamp,
                    'overlay_visible': visible is not None, 'identity_state': state, 'reason': reason}) + '\n')
                count += 1
        if not count:
            raise ValueError('Video contains no decodable frames')
        if declared_frames > 0 and count != declared_frames:
            raise ValueError(f'Decoded {count} frames, but container declares {declared_frames}; review incomplete')
        if len(event_times) != len(events):
            raise ValueError('Some annotated event frames are outside the decoded video')
        # No fake post-event frames at EOF. Incomplete windows remain unknown.
        rows.extend(decision_row(d, events, event_times) for d in scheduler.reject_pending('video_ended', now_s=previous_time))
    except Exception as exc:
        summary_path.write_text(json.dumps({'status': 'failed', 'video_sha256': source_sha,
                                           'error': str(exc)}, indent=2), encoding='utf-8')
        raise
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        adapter.close()
    summary = {'status': 'complete', 'video': str(video), 'video_sha256': source_sha,
               'source_unchanged': hashlib.sha256(video.read_bytes()).hexdigest() == source_sha,
               'clock_domain': 'video_pts', 'grid_pairing': 'not_verified_no_paired_grid_timestamps',
               'frames': count, 'inferences': inferred, 'poses': poses, 'identity_states': dict(states),
               'elapsed_seconds': time.perf_counter() - started, 'reviewer': reviewer,
               'metrics': score_events(rows),
               'scenarios': {s: score_events([r for r in rows if r['scenario'] == s]) for s in sorted({r['scenario'] for r in rows})},
               'limitations': ['Independent manual frame anchors are video-only, not optical touch events.',
                               'No human annotations means accuracy is unmeasured, not zero or perfect.',
                               'Identity continuity does not establish absolute anatomical truth.',
                               'Overlay uses nominal FPS; use burned-in source frame indices/PTS for VFR review.',
                               'All-frame offline inference does not measure live queueing or camera latency.']}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'events.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    template = output_dir / 'manual_template.json'
    if not template.exists():
        template.write_text(json.dumps({'video_sha256': source_sha, 'timebase': 'zero_based_video_frame_index',
                                       'reviewer': '', 'events': []}, indent=2), encoding='utf-8')
    return summary


def decision_row(decision, events, event_times):
    event = next(e for e in events if e['event_id'] == decision.event_id)
    return {'event_id': decision.event_id, 'frame_index': event['frame_index'],
            'video_time_s': event_times[decision.event_id], 'ground_truth': event.get('ground_truth', ''),
            'scenario': event.get('scenario', 'unspecified'), 'note': event.get('note', ''),
            'prediction': decision.label.value, 'confidence': decision.confidence, 'reason': decision.reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--model', type=Path)
    args = parser.parse_args()
    result = replay_video(args.video, args.output_dir, annotations=args.annotations, model=args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
