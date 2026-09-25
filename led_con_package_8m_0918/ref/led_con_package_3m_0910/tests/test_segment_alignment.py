import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_capture import APP
from hardware.usb_worker_3m import UsbWorker, E_DATA_REPORT

# Wire order: 2m (known failed bit 0), 3m, 1m.
BASE = bytes([254]) + bytes([255]) * 35


class SegmentAlignmentTests(unittest.TestCase):
    def worker(self):
        worker = UsbWorker(expected_payload_bytes=36, required_dark_bits=(0,))
        worker.led_interval = 0
        worker.log_interval = 0
        output = []
        worker.data_received.connect(output.append)
        return worker, output

    def feed(self, worker, payload, start):
        for dt in (0, 0.006, 0.012, 0.030):
            with patch('hardware.usb_worker_3m.time.perf_counter', return_value=start + dt):
                worker._process_payload(payload)

    def test_persistent_rotation_never_replaces_correct_segments(self):
        worker, output = self.worker()
        self.feed(worker, BASE, 0)
        count = len(output)
        for start, offset in ((0.1, 12), (0.2, 24)):
            self.feed(worker, BASE[offset:] + BASE[:offset], start)
            self.assertEqual(len(output), count)
        self.feed(worker, BASE, 0.3)
        self.assertGreater(len(output), count)
        self.assertEqual(set(output), {(BASE[24:] + BASE[:24]).hex(' ')})

    def test_starting_with_rotated_data_does_not_lock_wrong_baseline(self):
        worker, output = self.worker()
        self.feed(worker, BASE[12:] + BASE[:12], 0)
        self.assertEqual(output, [])
        self.feed(worker, BASE, 0.1)
        self.assertTrue(output)

    def test_real_obstruction_retains_known_failed_led(self):
        worker, output = self.worker()
        self.feed(worker, BASE, 0)
        blocked = bytearray(BASE)
        blocked[12:24] = bytes(12)
        self.feed(worker, bytes(blocked), 0.1)
        self.assertEqual(output[-1], (bytes(blocked[24:]) + bytes(blocked[:24])).hex(' '))

    def test_unequal_node_packet_sizes_cannot_shift_boundaries(self):
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        output = []
        worker.raw_contact_3m_signal.connect(lambda *args: output.append(args))
        for index, size in enumerate((11, 13, 12)):
            worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                frameIdx=1, packNum=3, packIdx=index,
                buffer=bytes([254]) * size, bufferLen=size), None)
        self.assertEqual(output, [])


if __name__ == '__main__':
    unittest.main()
