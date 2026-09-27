from pathlib import Path

import cv2
import numpy as np
import pytest

from camera.avi_video import AviVideo


def make_avi(tmp_path, count=12, times=None, name="clip.avi"):
    path = Path(tmp_path) / name
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    assert writer.isOpened()
    for index in range(count):
        writer.write(np.full((48, 64, 3), index * 20, np.uint8))
    writer.release()
    if times is not None:
        np.save(path.with_suffix(".timestamps.npy"), np.asarray(times, dtype=np.float64))
    return path


def test_random_access_reads_actual_frame_content_and_bounds_cache(tmp_path):
    path = make_avi(tmp_path, times=np.arange(12) ** 2 / 100)
    video = AviVideo(path)
    try:
        assert video.info.time_source == "采样时间"
        assert video.info.times[-1] == 1.21
        for index in [0, 11, 10, 2, *range(12), 0]:
            assert abs(float(video.read(index).mean()) - index * 20) < 3
        assert len(video._cache) == 8
        for index in (-1, 12):
            with pytest.raises(IndexError):
                video.read(index)
    finally:
        video.close()


@pytest.mark.parametrize("bad_times", [None, [0, 0.1], [0, 0.1, float('nan')], [0, 0.2, 0.1], [0, 0, 0.1], [[0, 0.1, 0.2]], [1, 2, 3]])
def test_missing_or_invalid_times_fall_back(tmp_path, bad_times):
    path = make_avi(tmp_path, count=3, times=bad_times)
    video = AviVideo(path)
    try:
        assert video.info.time_source == "时间按帧率估算"
        assert video.info.warning
        np.testing.assert_allclose(video.info.times, [0, 0.1, 0.2])
    finally:
        video.close()


def test_corrupt_and_pickle_time_files_are_not_loaded(tmp_path):
    path = make_avi(tmp_path, count=1)
    sidecar = path.with_suffix(".timestamps.npy")
    sidecar.write_bytes(b"broken numpy data")
    video = AviVideo(path)
    assert video.info.warning == "逐帧时间文件无效"
    video.close()
    np.save(sidecar, np.array([{"value": 1}], dtype=object))
    video = AviVideo(path)
    assert video.info.time_source == "时间按帧率估算"
    video.close()
    with sidecar.open("wb") as file:
        np.savez(file, times=[0.0])
    video = AviVideo(path)
    assert video.info.time_source == "时间按帧率估算"
    video.close()


def test_single_frame_and_missing_video(tmp_path):
    video = AviVideo(make_avi(tmp_path, count=1, times=[0]))
    assert video.info.times.tolist() == [0]
    assert video.read(0).shape == (48, 64, 3)
    video.close()
    with pytest.raises(ValueError):
        AviVideo(tmp_path / "missing.avi")


@pytest.mark.parametrize("with_times", [False, True])
def test_invalid_fps_requires_capture_times(tmp_path, monkeypatch, with_times):
    path = make_avi(tmp_path, count=2, times=[0, 0.2] if with_times else None)
    real_capture = cv2.VideoCapture

    class InvalidFps:
        def __init__(self, path):
            self.cap = real_capture(path)

        def get(self, prop):
            return float("nan") if prop == cv2.CAP_PROP_FPS else self.cap.get(prop)

        def __getattr__(self, name):
            return getattr(self.cap, name)

    monkeypatch.setattr(cv2, "VideoCapture", InvalidFps)
    if with_times:
        video = AviVideo(path)
        assert video.info.time_source == "采样时间"
        video.close()
    else:
        with pytest.raises(ValueError, match="有效帧率"):
            AviVideo(path)
