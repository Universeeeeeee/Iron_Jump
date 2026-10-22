"""Guard the experimental same-thread callback substitution."""
import pytest
from qtpy.QtCore import QObject, Signal, Slot
from quality_dispatch import Dispatch


class Engine(QObject):
    def __init__(self):
        super().__init__()
        self.received = []

    @Slot(object, object, bool)
    def process_quality_frame(self, raw, processed, uncertain):
        self.received.append((raw, processed, uncertain))


class Quality(QObject):
    frame_ready = Signal(object, object, bool)


@pytest.mark.parametrize('mode', ['qt', 'python'])
def test_preserves_arguments_once_on_same_thread(qapp, mode):
    engine = Engine()
    quality = Quality(engine)
    dispatch = Dispatch(quality, quality.frame_ready, mode)
    dispatch.connect(engine.process_quality_frame)
    raw, processed = object(), object()
    dispatch.emit(raw, processed, True)
    assert engine.received == [(raw, processed, True)]
    assert dispatch.count == 1 and dispatch.tid is not None
    with pytest.raises(AssertionError):
        dispatch.connect(engine.process_quality_frame)


def test_rejects_wrong_receiver_and_thread_before_delivery(qapp):
    engine, other = Engine(), Engine()
    quality = Quality(engine)
    dispatch = Dispatch(quality, quality.frame_ready, 'python')
    with pytest.raises(AssertionError):
        dispatch.connect(other.process_quality_frame)
    dispatch.connect(engine.process_quality_frame)
    dispatch.tid = -1
    with pytest.raises(AssertionError):
        dispatch.emit(None, None, False)
    assert not engine.received and dispatch.count == 0
