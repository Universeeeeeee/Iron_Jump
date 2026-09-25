import struct
import unittest
from test_capture import APP
from hardware.protocol import protocol_parser, crc8_poly_07, E_DATA_REPORT
from hardware.usb_worker_3m import UsbWorker


def packet(index, body=None, count=1, part=0):
    body = body if body is not None else bytes([254]) + bytes([255]) * 35
    payload = struct.pack('>IBB', index, count, part) + body
    region = bytes([E_DATA_REPORT]) + struct.pack('<H', len(payload)) + payload
    return bytes([90]) * 4 + region + bytes([crc8_poly_07(region)]) + bytes([165]) * 4


def drain(buffer):
    frames = []
    while True:
        result = protocol_parser(buffer)
        if result[0] != 0:
            return frames
        frames.append(result)


class StreamFramingTests(unittest.TestCase):
    def test_corrupt_large_length_does_not_block_next_frame(self):
        bad = bytearray(packet(1))
        bad[5:7] = bytes([255, 255])
        self.assertEqual([r[3].frameIdx for r in drain(bytearray(bad + packet(2)))], [2])

    def test_missing_byte_does_not_consume_next_header(self):
        bad = packet(1)
        bad = bad[:20] + bad[21:]
        self.assertEqual([r[3].frameIdx for r in drain(bytearray(bad + packet(2)))], [2])

    def test_frame_tail_is_checked_at_length_offset_not_first_magic(self):
        body = bytes([90]) * 4 + bytes([165]) * 4 + bytes([255]) * 28
        decoded = drain(bytearray(packet(1, body)))
        self.assertEqual(decoded[0][3].buffer, body)

    def test_every_possible_usb_split_keeps_complete_frame(self):
        data = packet(1) + packet(2)
        for split in range(1, len(data)):
            buffer = bytearray(data[:split])
            decoded = drain(buffer)
            buffer.extend(data[split:])
            decoded.extend(drain(buffer))
            self.assertEqual([r[3].frameIdx for r in decoded], [1, 2])

    def test_1000_frames_per_second_with_batched_usb_reads(self):
        data = b''.join(packet(i) for i in range(1000))
        buffer = bytearray()
        ids = []
        for offset in range(0, len(data), 137):
            buffer.extend(data[offset:offset + 137])
            ids.extend(r[3].frameIdx for r in drain(buffer))
        self.assertEqual(ids, list(range(1000)))
        self.assertEqual(buffer, bytearray())

    def test_noise_is_bounded_but_partial_header_is_retained(self):
        buffer = bytearray(b'noise' * 10000 + b'ZZZ')
        drain(buffer)
        self.assertEqual(buffer, bytearray(b'ZZZ'))
        buffer.extend(packet(4)[3:])
        self.assertEqual(drain(buffer)[0][3].frameIdx, 4)

    def test_duplicate_and_late_completed_frames_are_discarded(self):
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        observed = []
        worker.raw_contact_3m_signal.connect(lambda *args: observed.append(args))
        for index in (10, 11, 10, 11, 12):
            r = drain(bytearray(packet(index)))[0]
            worker._on_frame(*r[1:])
        self.assertEqual(len(observed), 3)

    def test_frame_sequence_wraparound_is_valid(self):
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        observed = []
        worker.raw_contact_3m_signal.connect(lambda *args: observed.append(args))
        for index in (0xFFFFFFFE, 0xFFFFFFFF, 0, 1):
            r = drain(bytearray(packet(index)))[0]
            worker._on_frame(*r[1:])
        self.assertEqual(len(observed), 4)


    def test_reader_uses_1ms_timeout_and_preserves_batched_frame_order(self):
        import threading
        from unittest.mock import patch
        from hardware.receive import CyUsbInterfaceDevice
        stream = b''.join(packet(i) for i in range(1000))
        chunks = iter(stream[i:i + 137] for i in range(0, len(stream), 137))
        done = threading.Event()

        class FakeDLL:
            def __init__(self):
                self.timeout = None
            def set_timeout(self, ms):
                self.timeout = ms
            def bytes_available(self):
                return 137
            def read(self, size):
                return next(chunks, b'')
            def write(self, data):
                return len(data)

        dll = FakeDLL()
        with patch('hardware.receive.CyUsbInterfaceDLL', return_value=dll):
            dev = CyUsbInterfaceDevice()
        dev._rx_buf.extend(b'previous capture garbage')
        ids = []
        def on_frame(kind, ack, subpack, status):
            ids.append(subpack.frameIdx)
            if len(ids) == 1000:
                dev._stop_evt.set()
                done.set()
        dev.set_on_frame(on_frame)
        dev.start_auto_read(137, timeout_ms=1)
        try:
            self.assertTrue(done.wait(5))
            self.assertEqual(ids, list(range(1000)))
            self.assertEqual(dll.timeout, 1)
            worker = UsbWorker(timeout_ms=1)
            worker.dev = dev
            self.assertTrue(worker._send_capture_cmd(True))
            self.assertEqual(dll.timeout, 1)
        finally:
            dev.stop_auto_read()


if __name__ == '__main__':
    unittest.main()
