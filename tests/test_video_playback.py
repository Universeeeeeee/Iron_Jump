import threading

import numpy as np
import pytest

from camera.avi_video import AviVideo
from ui.video_playback import VideoPlayback
from tests.test_avi_video import make_avi


@pytest.fixture
def playback(qtbot):
    player = VideoPlayback()
    yield player
    player.shutdown()


def open_player(qtbot, player, path):
    player.open(path)
    qtbot.waitUntil(lambda: player.info is not None)


def test_clock_speed_pause_step_end_and_restart(tmp_path, qtbot, playback):
    now = [100.0]
    playback._clock = lambda: now[0]
    path = make_avi(tmp_path, count=5, times=[0, 0.1, 0.3, 0.6, 1.0])
    frames = []
    playback.frame_ready.connect(lambda frame, index, stamp: frames.append((frame.mean(), index, stamp)))
    open_player(qtbot, playback, path)
    playback.set_rate(0.5)
    playback.play()
    now[0] += 0.65
    playback._tick()
    qtbot.waitUntil(lambda: playback.index == 2)
    assert frames[-1] == (40, 2, 0.3)
    playback.pause()
    now[0] += 50
    playback._tick()
    assert playback.index == 2
    playback.set_rate(0.25)
    playback.play()
    now[0] += 1.3
    playback._tick()
    qtbot.waitUntil(lambda: playback.index == 3)
    playback.set_rate(1.0)
    now[0] += 0.5
    playback._tick()
    qtbot.waitUntil(lambda: playback.index == 4 and not playback.playing)
    playback.play()
    qtbot.waitUntil(lambda: playback.index == 0)
    playback.step(-1)
    qtbot.waitUntil(lambda: not playback._busy)
    assert playback.index == 0 and not playback.playing
    playback.step(1)
    playback.step(1)
    qtbot.waitUntil(lambda: playback.index == 2)
    playback.seek(999)
    qtbot.waitUntil(lambda: playback.index == 4)
    playback.step(1)
    qtbot.waitUntil(lambda: not playback._busy)
    assert playback.index == 4


def test_scrubbing_coalesces_and_close_rejects_late_frames(tmp_path, qtbot, playback, monkeypatch):
    path = make_avi(tmp_path)
    open_player(qtbot, playback, path)
    entered = threading.Event()
    release = threading.Event()
    reads = []
    real_read = AviVideo.read

    def slow_read(video, index):
        reads.append(index)
        if index == 1:
            entered.set()
            release.wait(2)
        return real_read(video, index)

    monkeypatch.setattr(AviVideo, "read", slow_read)
    delivered = []
    playback.frame_ready.connect(lambda frame, index, time: delivered.append(index))
    try:
        playback.seek(1)
        qtbot.waitUntil(entered.is_set)
        playback.seek(2)
        playback.seek(3)
        playback.seek(7)
        release.set()
        qtbot.waitUntil(lambda: playback.index == 7)
        assert reads == [1, 7]
        assert delivered == [7]
        entered.clear()
        release.clear()
        playback.seek(1)
        qtbot.waitUntil(entered.is_set)
        playback.close()
        release.set()
        qtbot.wait(50)
        assert delivered == [7]
        assert playback.info is None
        open_player(qtbot, playback, path)
        assert delivered[-1] == 0
    finally:
        release.set()


def test_decode_failure_pauses_without_emitting_wrong_frame(tmp_path, qtbot, playback, monkeypatch):
    open_player(qtbot, playback, make_avi(tmp_path))
    frames = []
    errors = []
    playback.frame_ready.connect(lambda *args: frames.append(args))
    playback.error.connect(errors.append)

    def fail(video, index):
        raise RuntimeError("坏帧")

    monkeypatch.setattr(AviVideo, "read", fail)
    playback.seek(2)
    playback.play()
    qtbot.waitUntil(lambda: bool(errors))
    assert not playback.playing
    assert frames == []
    assert playback.index == 0


def test_single_frame_play_stops(tmp_path, qtbot, playback):
    open_player(qtbot, playback, make_avi(tmp_path, count=1, times=[0]))
    playback.play()
    qtbot.waitUntil(lambda: not playback.playing)
    assert playback.index == 0


def test_switch_file_discards_frame_from_previous_video(tmp_path, qtbot, playback, monkeypatch):
    first = make_avi(tmp_path, name="first.avi")
    second = make_avi(tmp_path, count=2, times=[0, 0.7], name="second.avi")
    open_player(qtbot, playback, first)
    entered = threading.Event()
    release = threading.Event()
    real_read = AviVideo.read

    def slow_read(video, index):
        if index == 8:
            entered.set()
            release.wait(2)
        return real_read(video, index)

    monkeypatch.setattr(AviVideo, "read", slow_read)
    frames = []
    playback.frame_ready.connect(lambda frame, index, stamp: frames.append(index))
    try:
        playback.seek(8)
        qtbot.waitUntil(entered.is_set)
        playback.open(second)
        release.set()
        qtbot.waitUntil(lambda: playback.info is not None and playback.info.frame_count == 2)
        assert frames == [0]
        assert playback.info.times.tolist() == [0, 0.7]
    finally:
        release.set()


def test_freeze_displayed_frame_invalidates_pending_decode(tmp_path, qtbot, playback, monkeypatch):
    open_player(qtbot, playback, make_avi(tmp_path))
    entered, release = threading.Event(), threading.Event()
    read = AviVideo.read
    delivered, pending = [], []

    def slow(video, index):
        if index == 2:
            entered.set()
            release.wait(2)
        return read(video, index)

    monkeypatch.setattr(AviVideo, 'read', slow)
    playback.frame_ready.connect(lambda frame, index, stamp: delivered.append(index))
    playback.pending_changed.connect(pending.append)
    try:
        playback.seek(2)
        qtbot.waitUntil(entered.is_set)
        assert playback.is_frame_pending
        assert playback.freeze_current_frame()
        assert not playback.is_frame_pending
        release.set()
        qtbot.wait(40)
        assert playback.index == 0 and delivered == []
        assert pending == [True, False]
        playback.step(1)
        qtbot.waitUntil(lambda: playback.index == 1)
    finally:
        release.set()
