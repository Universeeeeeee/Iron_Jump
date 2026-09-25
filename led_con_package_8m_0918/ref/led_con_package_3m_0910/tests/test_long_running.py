import tracemalloc
import unittest
from test_capture import APP
from test_stream_framing import packet, drain
from hardware.usb_worker_3m import UsbWorker


class LongRunningTests(unittest.TestCase):
    def test_worker_publishes_and_records_without_gui_signal_delivery(self):
        import tempfile
        from ui.capture_archive import CaptureArchive
        from hardware.capture_diagnostics import CaptureDiagnostics, LatestFrameMailbox

        with tempfile.TemporaryDirectory() as directory:
            archive = CaptureArchive()
            mailbox = LatestFrameMailbox()
            diagnostics = CaptureDiagnostics(directory, frame_sink=archive.append)
            diagnostics.start()
            worker = UsbWorker(
                expected_payload_bytes=36, stability_ms=0,
                display_mailbox=mailbox, diagnostics=diagnostics)
            body = bytes([1]) * 12 + bytes([2]) * 12 + bytes([4]) * 12
            worker._process_payload(body)
            worker._on_bytes(b"\x5a\x5a\x01")
            diagnostics.stop()
            try:
                latest = mailbox.take()
                self.assertEqual([node[0] for node in latest.nodes], [0, 1, 0])
                self.assertEqual(len(archive.frames), 1)
                self.assertEqual(next(iter(archive.frames))[:3], bytes([0, 0, 1]))
                self.assertEqual(diagnostics.dropped_raw_records, 0)
            finally:
                archive.close()

    def test_16bit_counter_wrap_does_not_freeze(self):
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        output = []
        worker.raw_contact_3m_signal.connect(lambda *args: output.append(args))
        for index in (65534, 65535, 0, 1, 2, 3):
            worker._on_frame(*drain(bytearray(packet(index)))[0][1:])
        self.assertEqual(len(output), 6)

    def test_large_counter_jump_does_not_poison_following_frames(self):
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        output = []
        worker.raw_contact_3m_signal.connect(lambda *args: output.append(args))
        for index in (10, 1000000, 11, 12, 13):
            worker._on_frame(*drain(bytearray(packet(index)))[0][1:])
        self.assertEqual(len(output), 5)

    def test_packet_index_base_cannot_switch_during_capture(self):
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        output = []
        worker.raw_contact_3m_signal.connect(lambda *args: output.append(args))
        for frame, base in ((1, 0), (2, 1), (3, 0)):
            for part in range(3):
                worker._on_frame(*drain(bytearray(packet(frame, bytes([1 << part]) * 12,
                                                         count=3, part=part + base)))[0][1:])
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0][:3], output[1][:3])

    def test_export_memory_is_bounded_without_losing_records(self):
        from ui.led_con_3m import SerialDataWidget
        widget = SerialDataWidget()
        widget._export_start_time = 0.0
        bits = [1] * 96
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        try:
            for _ in range(20000):
                widget._record_export(bits, [0] * 96, bits)
            retained = tracemalloc.get_traced_memory()[0] - before
            self.assertLess(retained, 1500000)
            self.assertEqual(len(widget._export_frames), 20000)
            self.assertEqual(len(widget._export_timestamps), 20000)
            self.assertTrue(all(frame == bytes(bits + [0] * 96 + bits)
                                for frame in widget._export_frames))
        finally:
            tracemalloc.stop()
            widget.close()


    def test_continuous_stream_across_two_wraps_with_concurrent_flush(self):
        import threading
        from qtpy.QtCore import Qt
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        worker.led_interval = 0
        observed = [0]
        errors = []
        def inspect(a, b, c):
            values = [sum(bit << i for i, bit in enumerate(node[:8])) for node in (a, b, c)]
            if values[0] != values[1] + 2 or values[2] != values[1] + 1:
                errors.append(values)
            observed[0] += 1
        worker.led_bits_3m_signal.connect(inspect, Qt.DirectConnection)
        stop = threading.Event()
        def refresh():
            while not stop.wait(0.001):
                worker._maybe_flush(force=True)
        refresher = threading.Thread(target=refresh)
        refresher.start()
        count = 131080
        try:
            for index in range(count):
                value = index % 200
                body = bytes([value]) * 12 + bytes([value + 1]) * 12 + bytes([value + 2]) * 12
                worker._on_frame(*drain(bytearray(packet(index & 65535, body)))[0][1:])
        finally:
            stop.set()
            refresher.join(5)
        self.assertFalse(refresher.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(observed[0], count)
        self.assertLessEqual(len(worker._recent_frames), 64)
        self.assertEqual(worker._frames, {})


if __name__ == '__main__':
    unittest.main()
