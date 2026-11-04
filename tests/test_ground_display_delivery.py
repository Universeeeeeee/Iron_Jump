"""The latest tracked footprint must paint while statistics are still busy."""
import threading

from qtpy.QtCore import QObject, QThread, Signal, Slot, Qt

from engine.overground_session import OvergroundSession
from tests.test_ground_fast_footprints import make, frame
from ui.ground_track import GroundChannelWidget
from ui.session_controller import SessionController


def test_connected_onset_group_does_not_wait_for_formal_confirmation(qapp):
    p = make('run')
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    visuals = []
    session.visual.connect(visuals.append)
    for n in range(114):
        groups = [(40, 40), (42, 42)] if n == 100 else [(40, 60)] if n > 100 else []
        session.on_frame(frame(p, n, groups))
    assert visuals[-1]['feet']
    assert all(f['status'] == 'candidate' for f in visuals[-1]['feet'])
    assert session.processor.reliable_touch_count == 0


def test_visual_is_published_before_expensive_summary(qapp):
    p = make('run')
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    for n in range(112):
        session.on_frame(frame(p, n, [(40, 60)] if n >= 100 else []))
    visuals = []
    session.visual.connect(visuals.append)
    original = session.processor.summary
    def summary():
        assert visuals and visuals[-1]['feet']
        return original()
    session.processor.summary = summary
    session._last_update_ns = 0
    session.on_frame(frame(p, 112, [(40, 60)]))


def test_display_discards_superseded_frames_and_discard_clears_pending(qtbot):
    controller = SessionController()
    controller._start_ground_visuals()
    received = []
    controller.footprint_visual_frame.connect(received.append)
    for n in range(100):
        controller._queue_ground_visual({'sample_index': n, 'feet': []})
    qtbot.waitUntil(lambda: bool(received))
    assert [v['sample_index'] for v in received] == [99]
    controller._queue_ground_visual({'sample_index': 100, 'feet': []})
    controller.discard()
    qtbot.wait(30)
    assert [v['sample_index'] for v in received] == [99]
    assert not controller._visual_timer.isActive()


def test_candidate_actually_paints_before_worker_summary_returns(qtbot):
    painted = threading.Event()
    released = threading.Event()
    blocked = threading.Event()
    class Channel(GroundChannelWidget):
        def paintEvent(self, event):
            super().paintEvent(event)
            if self._feet:
                painted.set()
    channel = Channel()
    qtbot.addWidget(channel)
    channel.resize(280, 700)
    channel.show()
    controller = SessionController()
    controller._start_ground_visuals()
    controller.footprint_visual_frame.connect(channel.render_state)
    p = make('run')
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    session.visual.connect(controller._queue_ground_visual, Qt.DirectConnection)
    for n in range(112):
        session.on_frame(frame(p, n, [(40, 60)] if n >= 100 else []))
    original = session.processor.summary
    def slow_summary():
        blocked.set()
        released.wait(2)
        return original()
    session.processor.summary = slow_summary
    session._last_update_ns = 0
    class Worker(QObject):
        done = Signal()
        @Slot()
        def run(self):
            session.on_frame(frame(p, 112, [(40, 60)]))
            self.done.emit()
    thread = QThread()
    worker = Worker()
    worker.moveToThread(thread)
    session.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(thread.quit, Qt.DirectConnection)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(session.deleteLater)
    thread.start()
    try:
        qtbot.waitUntil(blocked.is_set)
        qtbot.waitUntil(painted.is_set, timeout=500)
        assert not released.is_set()
        assert channel._feet[0]['status'] == 'candidate'
    finally:
        released.set()
        thread.quit()
        assert thread.wait(3000)
        controller.discard()


def test_ground_icon_size_and_cached_pixels_ignore_measured_length(qtbot):
    channel = GroundChannelWidget(overview=False)
    qtbot.addWidget(channel)
    channel.resize(280, 700)
    channel.show()
    assert channel._foot_size_for_lane(200, 600, 5) == channel._foot_size_for_lane(200, 600, 35)
    state = {'positions_m': make('run').positions, 'contact_bits': [0] * 768,
             'valid_bits': [1] * 768, 'feet': [{'status': 'candidate', 'side': 'unknown',
             'centroid_cm': 100, 'length_cm': 5, 'shape_valid': True}]}
    channel.render_state(state)
    first = channel.grab().toImage()
    sprites = dict(channel._foot_sprites)
    for position, length in [(102, 10), (105, 20), (100, 35)]:
        state['feet'][0].update(centroid_cm=position, length_cm=length)
        channel.render_state(state)
        last = channel.grab().toImage()
    assert channel._foot_sprites == sprites
    assert last == first
