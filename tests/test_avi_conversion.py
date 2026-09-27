import csv

import cv2
import numpy as np
import pytest

from tests.test_tinyse_camera_widget import _install_camera_dependency_stubs

_install_camera_dependency_stubs()
from camera.tinyse_camera import mjpg_to_avi


def make_raw(tmp_path, bad_indices=()):
    raw = tmp_path / "sample.mjpg"
    index_path = raw.with_suffix(".csv")
    times = [5.0, 5.01, 5.04, 5.08]
    rows = []
    with raw.open("wb") as file:
        for index, stamp in enumerate(times):
            if index in bad_indices:
                jpeg = b"broken jpeg"
            else:
                ok, encoded = cv2.imencode(".jpg", np.full((48, 64, 3), index * 60, np.uint8))
                assert ok
                jpeg = encoded.tobytes()
            rows.append((file.tell(), len(jpeg), stamp))
            file.write(jpeg)
    with index_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["offset", "length", "sample_time"])
        writer.writerows(rows)
    return raw, index_path


@pytest.mark.parametrize("bad_indices", [(), (1,), (0,)])
def test_conversion_delivers_matching_images_and_times_then_cleans(tmp_path, bad_indices):
    raw, index = make_raw(tmp_path, bad_indices)
    avi = mjpg_to_avi(raw, index)
    capture = cv2.VideoCapture(str(avi))
    means = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        means.append(frame.mean())
    capture.release()
    good = [i for i in range(4) if i not in bad_indices]
    np.testing.assert_allclose(means, [i * 60 for i in good], atol=3)
    times = np.asarray([5, 5.01, 5.04, 5.08])[good]
    np.testing.assert_allclose(np.load(avi.with_suffix(".timestamps.npy"), allow_pickle=False), times - times[0])
    assert set(path.name for path in tmp_path.iterdir()) == {"sample.avi", "sample.timestamps.npy"}


def test_time_save_failure_preserves_originals(tmp_path, monkeypatch):
    raw, index = make_raw(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(np, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        mjpg_to_avi(raw, index)
    assert raw.exists() and index.exists()
    assert not raw.with_suffix(".timestamps.npy").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_all_bad_frames_preserves_originals(tmp_path):
    raw, index = make_raw(tmp_path, range(4))
    with pytest.raises(RuntimeError, match="没有可解码"):
        mjpg_to_avi(raw, index)
    assert raw.exists() and index.exists()


def test_avi_validation_failure_preserves_originals(tmp_path, monkeypatch):
    raw, index = make_raw(tmp_path)
    real_capture = cv2.VideoCapture

    class WrongCount:
        def __init__(self, path):
            self.cap = real_capture(path)

        def get(self, prop):
            return 3 if prop == cv2.CAP_PROP_FRAME_COUNT else self.cap.get(prop)

        def __getattr__(self, name):
            return getattr(self.cap, name)

    monkeypatch.setattr(cv2, "VideoCapture", WrongCount)
    with pytest.raises(RuntimeError, match="帧数校验失败"):
        mjpg_to_avi(raw, index)
    assert raw.exists() and index.exists()
