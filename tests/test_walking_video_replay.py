import hashlib
import json

import cv2
import numpy as np
import pytest

from tests.test_walking_vision_pipeline import landing_pose
from tools.replay_walking_video import load_manual_events, replay_video, score_events


def make_video(path, frames=28):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 20, (640, 360))
    assert writer.isOpened()
    for _ in range(frames):
        writer.write(np.zeros((360, 640, 3), dtype=np.uint8))
    writer.release()


class Adapter:
    def __init__(self, _model):
        pass
    def open(self):
        pass
    def close(self):
        pass
    def infer_bgr(self, frame, timestamp_ms):
        return landing_pose(timestamp_ms)


def test_video_pipeline_preserves_source_and_distinguishes_unknown_from_wrong(tmp_path):
    video = tmp_path / 'fixture.mp4'
    make_video(video)
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    annotations = tmp_path / 'manual.json'
    annotations.write_text(json.dumps({'video_sha256': digest, 'reviewer': 'synthetic test fixture',
        'timebase': 'zero_based_video_frame_index', 'events': [
            {'event_id': 1, 'frame_index': 20, 'ground_truth': 'left', 'scenario': 'normal'},
            {'event_id': 2, 'frame_index': 27, 'ground_truth': 'right', 'scenario': 'eof'}]}))
    result = replay_video(video, tmp_path / 'out', annotations=annotations, adapter_factory=Adapter)
    assert result['source_unchanged']
    assert result['frames'] == 28
    assert result['metrics']['correct'] == 1
    assert result['metrics']['unknown'] == 1
    assert result['metrics']['wrong'] == 0
    assert result['metrics']['coverage'] == .5
    rows = json.loads((tmp_path / 'out/events.json').read_text())
    assert rows[1]['reason'] == 'video_ended'
    capture = cv2.VideoCapture(str(tmp_path / 'out/overlay.mp4'))
    delivered = 0
    while capture.read()[0]:
        delivered += 1
    capture.release()
    assert delivered == 28  # Read the encoded result, not just VideoWriter's status.
    assert hashlib.sha256(video.read_bytes()).hexdigest() == digest


def test_unlabelled_video_has_no_accuracy_and_keeps_annotation_template(tmp_path):
    video = tmp_path / 'fixture.mp4'
    make_video(video, 5)
    result = replay_video(video, tmp_path / 'out', adapter_factory=Adapter)
    assert result['metrics']['accuracy'] is None
    assert result['metrics']['accepted_accuracy'] is None
    assert result['grid_pairing'].startswith('not_verified')
    template = tmp_path / 'out/manual_template.json'
    original = template.read_bytes()
    replay_video(video, tmp_path / 'out', adapter_factory=Adapter)
    assert template.read_bytes() == original


@pytest.mark.parametrize('change', [
    {'video_sha256': 'wrong'}, {'timebase': 'host'}, {'reviewer': ''},
    {'events': [{'event_id': 1, 'frame_index': -1}]},
    {'events': [{'event_id': 1, 'frame_index': 2, 'ground_truth': 'both'}]},
    {'events': [{'event_id': 1, 'frame_index': 2}, {'event_id': 1, 'frame_index': 3}]},
])
def test_annotations_reject_mismatched_or_invalid_labels(tmp_path, change):
    data = {'video_sha256': 'source', 'timebase': 'zero_based_video_frame_index',
            'reviewer': 'reviewer', 'events': [{'event_id': 1, 'frame_index': 2, 'ground_truth': 'left'}]}
    data.update(change)
    path = tmp_path / 'annotation.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_manual_events(path, 'source')


def test_failure_replaces_old_success_summary_and_cannot_overwrite_truth(tmp_path):
    video = tmp_path / 'fixture.mp4'
    make_video(video, 5)
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    output = tmp_path / 'out'
    replay_video(video, output, adapter_factory=Adapter)
    annotations = tmp_path / 'manual.json'
    annotations.write_text(json.dumps({'video_sha256': digest, 'reviewer': '',
        'timebase': 'zero_based_video_frame_index', 'events': [{'event_id': 1, 'frame_index': 999}]}))
    with pytest.raises(ValueError, match='outside'):
        replay_video(video, output, annotations=annotations, adapter_factory=Adapter)
    assert json.loads((output / 'summary.json').read_text())['status'] == 'failed'
    with pytest.raises(ValueError, match='overwrite'):
        replay_video(video, output, annotations=output / 'events.json', adapter_factory=Adapter)


def test_metrics_list_confident_errors_without_scoring_unlabelled_predictions():
    rows = [{'event_id': i, 'ground_truth': truth, 'prediction': prediction, 'confidence': .99}
            for i, truth, prediction in [(1, 'left', 'right'), (2, '', 'left'), (3, 'right', 'unknown')]]
    metrics = score_events(rows)
    assert metrics['wrong_event_ids'] == metrics['high_confidence_wrong_ids'] == [1]
    assert metrics['unscored_events'] == 1
    assert metrics['unknown'] == 1


def test_encoded_video_actually_removes_old_skeleton_when_person_disappears(tmp_path):
    class MissingAdapter(Adapter):
        def infer_bgr(self, frame, timestamp_ms):
            return landing_pose(timestamp_ms) if timestamp_ms < 100 else None

    video = tmp_path / 'fixture.mp4'
    make_video(video, 5)
    output = tmp_path / 'out'
    result = replay_video(video, output, adapter_factory=MissingAdapter)
    assert result['frames'] == 5
    states = [json.loads(line) for line in (output / 'frames.jsonl').read_text().splitlines()]
    assert [s['overlay_visible'] for s in states] == [True, True, False, False, False]
    capture = cv2.VideoCapture(str(output / 'overlay.mp4'))
    pixels = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        # Below the text band the input is black. Check decoded pixels rather
        # than trusting the overlay_visible flag or the drawing function's return.
        pixels.append(np.count_nonzero(cv2.cvtColor(frame[80:], cv2.COLOR_BGR2GRAY) > 40))
    capture.release()
    assert min(pixels[:2]) > 100
    assert pixels[2:] == [0, 0, 0]
