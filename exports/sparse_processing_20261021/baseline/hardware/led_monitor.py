"""Shared acquisition with raw recording and independent display-only confirmation."""
from dataclasses import dataclass
import os
import threading

from qtpy.QtCore import Qt, Signal, Slot

from hardware.beam_filter import BeamDisplayFilter
from hardware.active_segments import ActiveSegments
from hardware.usb_worker import UsbWorker

_INVERT = bytes.maketrans(b'\x00\x01', b'\x01\x00')


@dataclass(frozen=True)
class MonitorSnapshot:
    nodes: tuple
    segment_ids: tuple
    active_indices: tuple
    selection_complete: bool
    frames: int
    frame_index: int
    received_ns: int
    dropped_frames: int
    zero_frames: tuple
    transients: tuple


class MonitorMailbox:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = None

    def publish(self, snapshot):
        with self._lock:
            self._pending = snapshot

    def take(self):
        with self._lock:
            result, self._pending = self._pending, None
        return result


class MonitorWorker(UsbWorker):
    """Reuse native startup/parser, with no per-frame Qt list delivery to the UI."""
    stopped = Signal()

    def __init__(self, *, diagnostics=None, mailbox=None, stability_ms=None,
                 observation_samples=3000, **kwargs):
        super().__init__(**kwargs)
        self.diagnostics = diagnostics
        self.mailbox = mailbox or MonitorMailbox()
        self.display = BeamDisplayFilter(float(os.getenv('DAYU_FRAME_CONFIRM_MS', '10'))
                                         if stability_ms is None else stability_ms)
        self.selection = ActiveSegments(observation_samples)
        self._observation_samples = observation_samples
        self._selection_samples = 0
        self._selection_complete = False
        self._last_frame = None
        self._frames_received = 0
        self._dropped_frames = 0
        self._zero_frames = []
        self._display_payload = None
        self._nodes = ()
        self.acquisition_issue.connect(self._record_issue, Qt.DirectConnection)

    def _emit(self, message):
        # Detailed driver/protocol messages belong to the console and capture log.
        print(message, flush=True)
        if self.diagnostics is not None:
            self.diagnostics.log_status('device_message', message=message)

    def _on_bytes(self, data):
        if self.diagnostics is not None:
            self.diagnostics.record_raw(data)

    def _record_issue(self, issue):
        if self.diagnostics is not None:
            self.diagnostics.increment('acquisition_issues')
            self.diagnostics.log_status('acquisition_issue', code=issue.code,
                                        frame_index=issue.frame_index)

    def _publish_frame(self, frame):
        previous = self._last_frame
        if previous is None or previous.stream_id != frame.stream_id or previous.layout != frame.layout:
            self._frames_received = self._dropped_frames = self._selection_samples = 0
            self._selection_complete = False
            self._zero_frames = [0] * len(frame.layout.segments)
            self._display_payload = None
            if self.diagnostics is not None:
                self.diagnostics.log_status('layout', stream_id=frame.stream_id,
                    segment_ids=[s.segment_id for s in frame.layout.segments],
                    wire_indices=[s.wire_index for s in frame.layout.segments],
                    time_source=frame.time_source, recording='unfiltered_led_bits')
        self._last_frame = frame
        self._frames_received += 1
        self._dropped_frames += frame.dropped_frames_before
        if self.diagnostics is not None:
            self.diagnostics.record_frame(frame.contact_bits.translate(_INVERT), frame.sample_time_s)
        if not self._selection_complete:
            self.selection.observe(frame)
            if (previous is None or frame.sample_index != previous.sample_index + 1
                    or frame.stream_id != previous.stream_id):
                self._selection_samples = 0
            valid = (not frame.dropped_frames_before and all(frame.valid_bits)
                     and not any(flag != 'all_beams_blocked' for flag in frame.quality_flags))
            self._selection_samples = self._selection_samples + 1 if valid else 0
            self._selection_complete = self._selection_samples >= self._observation_samples
            if self._selection_complete and self.diagnostics is not None:
                self.diagnostics.log_status('segment_selection', **self.selection.snapshot())
        for i, segment in enumerate(frame.layout.segments):
            offset = segment.wire_index * 12
            self._zero_frames[i] += frame.wire_payload[offset:offset + 12] == bytes(12)
        payload = self.display.feed(frame)
        if payload != self._display_payload:
            bits = frame.layout.contact_bits(payload).translate(_INVERT)
            self._nodes = tuple(bits[i:i + 96] for i in range(0, len(bits), 96))
            self._display_payload = payload
        self.mailbox.publish(MonitorSnapshot(
            self._nodes, tuple(s.segment_id for s in frame.layout.segments),
            self.selection.indices, self._selection_complete, self._frames_received,
            frame.frame_index, frame.received_monotonic_ns, self._dropped_frames,
            tuple(self._zero_frames),
            tuple(self.display.transients[s.wire_index] for s in frame.layout.segments)))

    @Slot()
    def start(self):
        try:
            if self.diagnostics is not None:
                self.diagnostics.start()
                self.diagnostics.log_status('capture_starting', timeout_ms=self.timeout_ms,
                    chunk_size=self.chunk_size, display_confirmation_ms=self.display.samples)
            super().start()
        except Exception as exc:
            self._emit_state('error', f'采集启动失败: {exc}')
        if not self._capturing:
            self.stop()

    @Slot()
    def shutdown(self):
        """Distinct Qt entry point: do not queue an overridden inherited stop slot."""
        self.stop()

    @Slot()
    def stop(self):
        super().stop()
        if self.diagnostics is not None:
            self.diagnostics.request_stop()
        self.stopped.emit()
