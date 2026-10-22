"""Verify the direct-reader contract on an actual foreign Python thread."""
from types import SimpleNamespace
import threading
import pytest
from qtpy.QtCore import QObject, Signal, Slot, Qt
from ui.session_controller import _GroundFrameInbox
from source_dispatch import SourceDispatch


class Source(QObject):
    frame = Signal(object)


class Inbox(_GroundFrameInbox):
    @Slot(object)
    def on_frame(self, frame):
        self.callback_tid = threading.get_native_id()
        super().on_frame(frame)


@pytest.mark.parametrize('mode', ['qt', 'python'])
def test_reader_thread_and_frame_identity_are_preserved(qapp, mode):
    quality, source = QObject(), Source()
    inbox = Inbox(quality)
    dispatch = SourceDispatch(source.frame, mode)
    dispatch.connect(inbox.on_frame, Qt.DirectConnection)
    frame = SimpleNamespace(sample_index=123)
    producer = threading.Thread(target=dispatch.emit, args=(frame,))
    producer.start()
    producer.join(2)
    assert not producer.is_alive()
    assert inbox.callback_tid == dispatch.tid != threading.get_native_id()
    assert list(inbox._pending) == [(False, frame)]
    assert quality.latest_received_frame is frame and dispatch.count == 1


def test_rejects_queued_substitution(qapp):
    quality, source = QObject(), Source()
    inbox = Inbox(quality)
    dispatch = SourceDispatch(source.frame, 'python')
    with pytest.raises(AssertionError):
        dispatch.connect(inbox.on_frame, Qt.QueuedConnection)
    assert dispatch.callback is None
