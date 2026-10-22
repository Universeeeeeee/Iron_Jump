"""Synthetic packetization of retained payloads through original parser/UsbWorker.

Packetization and 20ms chunk timing are controls, not recorded USB traffic.
"""
import json
import os
from pathlib import Path
import time


def packets(sample, payload, segmented):
    from hardware.protocol import E_DATA_REPORT, crc8_poly_07
    count = len(payload) // 12 if segmented else 1
    chunks = [payload[i:i + 12] for i in range(0, len(payload), 12)] if segmented else [payload]
    result = []
    for part, chunk in enumerate(chunks, 1):
        body = int(sample).to_bytes(4, 'little') + bytes((count, part)) + chunk
        checked = bytes((E_DATA_REPORT,)) + len(body).to_bytes(2, 'little') + body
        result.append(b'\x5a' * 4 + checked + bytes((crc8_poly_07(checked),)) + b'\xa5' * 4)
    return b''.join(result)


def install(r):
    if os.environ.get('IJ_WIRE_SHAPE', 'decoded') == 'decoded':
        return
    from qtpy.QtCore import Qt
    from hardware.protocol import ProtocolParser
    from hardware.usb_worker import UsbWorker
    original_init = r.ReplayWorker.__init__

    def init(self, **kwargs):
        original_init(self, **kwargs)
        d = self.data
        self.wire_worker = UsbWorker(layout=d['layout'], legacy_frame_signals=False)
        self.wire_worker._assembler.stream_id = d['context'].stream_id
        self.wire_worker._assembler._sample_index = int(d['samples'][0])
        self.wire_worker._layout_announced = True
        # No connect_device/start_capture/native DLL calls. Health probe stays off.
        self.wire_worker.sensor_frame_received.connect(self.deliver_wire, Qt.DirectConnection)
        self.wire_errors = []
        self.wire_worker.acquisition_issue.connect(lambda value: self.wire_errors.append(repr(value)), Qt.DirectConnection)
        self.encoded = [packets(n, wire, os.environ['IJ_WIRE_SHAPE'] == 'segmented') for n, wire in zip(d['samples'], d['wire'])]

    def deliver(self, frame):
        d = self.data
        i = self.sent
        assert frame.frame_index == int(d['samples'][i])
        assert frame.sample_index == int(d['samples'][i])
        assert frame.contact_bits == d['bits'][i]
        assert frame.wire_payload == d['wire'][i]
        assert frame.valid_bits == self.wire_worker._assembler.valid_bits
        assert not frame.dropped_frames_before
        event = self.wire_events.get(frame.sample_index)
        if event:
            r.record('source_received', [event], ns=time.perf_counter_ns(), sample=frame.sample_index, nominal_ns=self.started_ns + i * 1_000_000)
        self.sensor_frame_received.emit(frame)
        self.sent += 1

    def feed(self):
        while not self.go.wait(.05):
            if self.stop_event.is_set():
                return
        self.started_ns = time.perf_counter_ns()
        self.wire_events = {e['published_sample']: e['event_id'] for e in self.data['events'].values()}
        parser = ProtocolParser()
        parser_errors = []
        parser.on_error = parser_errors.append
        buffer = bytearray()
        calls = byte_count = 0
        cpu_start = time.thread_time_ns()
        r.record('source_start', ns=self.started_ns)
        try:
            for offset in range(0, len(self.encoded), 20):
                remaining = (self.started_ns + offset * 1_000_000 - time.perf_counter_ns()) / 1e9
                if remaining > 0:
                    self.stop_event.wait(remaining)
                if self.stop_event.is_set():
                    break
                chunk = b''.join(self.encoded[offset:offset + 20])
                # Exercise original receive buffer with fixed 2048-byte reads,
                # including split packets. Original DLL availability is unknown.
                for begin in range(0, len(chunk), 2048):
                    data = chunk[begin:begin + 2048]
                    byte_count += len(data)
                    buffer.extend(data)
                    while True:
                        value = parser.parse(buffer)
                        calls += 1
                        if value[0] != 0:
                            break
                        self.wire_worker._on_frame(*value[1:])
            assert not buffer
            assert not self.wire_errors, self.wire_errors
        except Exception as exc:
            self.wire_errors.append(repr(exc))
            raise
        finally:
            r.record('source_end', sent=self.sent)
            out = Path(os.environ['IJ_REPLAY_OUTPUT'])
            out.mkdir(parents=True, exist_ok=True)
            (out / f'wire_{os.getpid()}.json').write_text(json.dumps(dict(
                shape=os.environ['IJ_WIRE_SHAPE'], verified_frames=self.sent,
                parser_calls=calls, bytes=byte_count, source_thread_cpu_ns=time.thread_time_ns() - cpu_start,
                parser_errors=parser_errors, errors=self.wire_errors,
                native_usb_opened=False, original_arrival_pattern_available=False,
            ), indent=2), encoding='utf-8')

    r.ReplayWorker.__init__ = init
    r.ReplayWorker.deliver_wire = deliver
    r.ReplayWorker.feed = feed
