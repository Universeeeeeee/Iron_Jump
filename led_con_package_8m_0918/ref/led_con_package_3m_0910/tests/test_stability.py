import json
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from test_capture import APP
from hardware.usb_worker_3m import UsbWorker


BASE = bytes.fromhex("ff " * 12 + "fe " + "ff " * 23)


def wire(normalized):
    return normalized[12:36] + normalized[:12]


class StabilityTests(unittest.TestCase):
    def worker(self):
        worker = UsbWorker(expected_payload_bytes=36)
        worker.led_interval = 0
        worker.log_interval = 0
        observed = []
        worker.data_received.connect(observed.append)
        return worker, observed

    def feed(self, worker, payload, timestamp):
        with patch('hardware.usb_worker_3m.time.perf_counter', return_value=timestamp):
            worker._process_payload(wire(payload))

    def test_recorded_unobstructed_stream_preserves_bad_led_without_flicker(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/unobstructed_20260907.json').read_text())
        patterns = [bytes.fromhex(p) for p in fixture['patterns']]
        worker, observed = self.worker()
        for timestamp, index in fixture['samples']:
            self.feed(worker, patterns[index], timestamp)
        self.assertGreater(len(observed), 5000)
        self.assertEqual(set(observed), {BASE.hex(' ')})

    def test_real_sustained_obstruction_and_release_are_accepted(self):
        worker, observed = self.worker()
        blocked = bytearray(BASE)
        blocked[4:6] = bytes(2)
        blocked = bytes(blocked)
        for offset, payload in ((0, BASE), (0.1, blocked), (0.2, BASE)):
            before = len(observed)
            self.feed(worker, payload, offset)
            self.feed(worker, payload, offset + 0.006)
            self.assertEqual(len(observed), before)
            self.feed(worker, payload, offset + 0.012)
            self.assertEqual(observed[-1], payload.hex(' '))

    def test_fast_duplicate_burst_does_not_confirm_glitch(self):
        worker, observed = self.worker()
        for t in (0, 0.006, 0.012):
            self.feed(worker, BASE, t)
        bad = BASE[:24] + bytes(12)
        for i in range(20):
            self.feed(worker, bad, 0.020 + i * 0.0001)
        self.feed(worker, BASE, 0.030)
        self.assertEqual(set(observed), {BASE.hex(' ')})

    def test_invalid_frame_interrupts_candidate_confirmation(self):
        worker, observed = self.worker()
        self.feed(worker, BASE, 0)
        self.feed(worker, BASE, 0.006)
        self.feed(worker, bytes(36), 0.010)
        self.feed(worker, BASE, 0.012)
        self.assertEqual(observed, [])


if __name__ == '__main__':
    unittest.main()
