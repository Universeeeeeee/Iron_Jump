import json
import math
from pathlib import Path

import pytest

from camera.video_annotations import VideoAnnotations, angle_degrees


@pytest.mark.parametrize('points,expected', [([[2, 0], [0, 0], [1, 0]], 0), ([[1, 0], [0, 0], [0, 1]], 90), ([[0, 1], [1, 1], [2, 1]], 180), ([[1, 0], [0, 0], [1, 1]], 45)])
def test_angles(points, expected):
    assert angle_degrees(points) == pytest.approx(expected)


def test_coincident_points_rejected():
    with pytest.raises(ValueError, match='重合'):
        angle_degrees([[0, 0], [0, 0], [1, 1]])


def angle():
    return {'id': 'a', 'kind': 'angle', 'frame': 1, 'points': [[10, 10], [30, 10], [30, 30]]}


def test_save_edit_delete_reload(tmp_path):
    path = tmp_path / 'test.avi'
    doc = VideoAnnotations(path, 10, 100, 100)
    doc.commit([angle(), {'id': 't', 'kind': 'interval', 'start': 1, 'end': 9}])
    assert VideoAnnotations(path, 10, 100, 100).records == doc.records
    changed = dict(angle(), points=[[20, 10], [30, 10], [30, 40]])
    doc.commit([changed])
    assert VideoAnnotations(path, 10, 100, 100).records == [changed]
    doc.commit([])
    assert VideoAnnotations(path, 10, 100, 100).records == []
    assert not list(tmp_path.glob('*.tmp'))


def test_failed_write_preserves_disk_and_memory(tmp_path, monkeypatch):
    doc = VideoAnnotations(tmp_path / 'test.avi', 10, 100, 100)
    doc.commit([angle()])
    original = doc.path.read_bytes()

    def fail(*args):
        raise PermissionError('read only')

    monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(PermissionError):
        doc.commit([])
    assert doc.records == [angle()]
    assert doc.path.read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('change', [lambda d: d.update(version=2), lambda d: d['video'].update(frame_count=11), lambda d: d['video'].update(width=101), lambda d: d['annotations'][0].update(frame=-1), lambda d: d['annotations'][0].update(points=[[math.nan, 0], [1, 1], [2, 3]])])
def test_invalid_documents_not_overwritten(tmp_path, change):
    path = tmp_path / 'test.avi'
    doc = VideoAnnotations(path, 10, 100, 100)
    doc.commit([angle()])
    data = json.loads(doc.path.read_text())
    change(data)
    doc.path.write_text(json.dumps(data))
    original = doc.path.read_bytes()
    with pytest.raises(ValueError):
        VideoAnnotations(path, 10, 100, 100)
    assert doc.path.read_bytes() == original


def test_invalid_interval_rejected(tmp_path):
    doc = VideoAnnotations(tmp_path / 'test.avi', 10, 100, 100)
    with pytest.raises(ValueError):
        doc.commit([{'id': 't', 'kind': 'interval', 'start': 2, 'end': 2}])
    assert not doc.path.exists()


def test_unwritable_directory_does_not_publish_new_record(tmp_path, monkeypatch):
    import camera.video_annotations as module

    doc = VideoAnnotations(tmp_path / 'clip.avi', 10, 100, 100)

    def fail(**kwargs):
        raise PermissionError('directory is read only')

    monkeypatch.setattr(module.tempfile, 'NamedTemporaryFile', fail)
    with pytest.raises(PermissionError):
        doc.commit([angle()])
    assert doc.records == []
    assert not doc.path.exists()
