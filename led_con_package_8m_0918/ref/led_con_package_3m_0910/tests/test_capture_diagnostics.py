import csv
import importlib
import tempfile
import time
import unittest
from pathlib import Path


class CaptureDiagnosticsTests(unittest.TestCase):
    def _types(self):
        try:
            module = importlib.import_module("hardware.capture_diagnostics")
        except ImportError as exc:
            self.fail(f"capture diagnostics module is missing: {exc}")
        return module.CaptureDiagnostics, module.LatestFrameMailbox

    def test_latest_frame_mailbox_replaces_old_frames_without_queueing(self):
        _, LatestFrameMailbox = self._types()
        mailbox = LatestFrameMailbox()

        for sequence in range(10_000):
            mailbox.publish(([sequence], [sequence + 1], [sequence + 2]))

        item = mailbox.take()
        self.assertEqual(item.sequence, 10_000)
        self.assertEqual(item.nodes, ([9_999], [10_000], [10_001]))
        self.assertIsNone(mailbox.take())

    def test_raw_chunks_are_written_to_rotating_csv_in_receive_order(self):
        CaptureDiagnostics, _ = self._types()
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = CaptureDiagnostics(directory, max_csv_bytes=150)
            diagnostics.start()
            expected = [bytes([index]) * 20 for index in range(8)]
            for data in expected:
                self.assertTrue(diagnostics.record_raw(data))
            diagnostics.stop()

            rows = []
            paths = sorted(Path(directory).glob("raw_*_part*.csv"))
            self.assertGreater(len(paths), 1)
            for path in paths:
                with path.open(encoding="utf-8", newline="") as stream:
                    rows.extend(csv.DictReader(stream))
            self.assertEqual([bytes.fromhex(row["raw_hex"]) for row in rows], expected)
            self.assertEqual([int(row["byte_count"]) for row in rows], [20] * 8)

    def test_status_log_records_state_and_periodic_counters(self):
        CaptureDiagnostics, _ = self._types()
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = CaptureDiagnostics(directory, heartbeat_seconds=0.02)
            diagnostics.start()
            diagnostics.log_status("capture_started", timeout_ms=1)
            diagnostics.increment("valid_frames", 3)
            time.sleep(0.05)
            diagnostics.stop()

            text = next(Path(directory).glob("status_*.log")).read_text(encoding="utf-8")
            self.assertIn("event=capture_started", text)
            self.assertIn("timeout_ms=1", text)
            self.assertIn("event=heartbeat", text)
            self.assertIn("valid_frames=3", text)

    def test_full_queue_drops_records_instead_of_blocking_receiver(self):
        CaptureDiagnostics, _ = self._types()
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = CaptureDiagnostics(directory, queue_capacity=1)
            started = time.perf_counter()
            self.assertTrue(diagnostics.record_raw(b"first"))
            self.assertFalse(diagnostics.record_raw(b"second"))
            elapsed = time.perf_counter() - started

            self.assertLess(elapsed, 0.05)
            self.assertEqual(diagnostics.dropped_raw_records, 1)
            diagnostics.start()
            diagnostics.stop()

    def test_valid_frames_are_archived_by_the_background_writer(self):
        CaptureDiagnostics, _ = self._types()
        captured = []
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = CaptureDiagnostics(
                directory, frame_sink=lambda timestamp, bits: captured.append((timestamp, bits)))
            diagnostics.start()
            bits = bytes([1, 0]) * 144
            self.assertTrue(diagnostics.record_frame(bits, timestamp=1.25))
            diagnostics.stop()

        self.assertEqual(captured, [(1.25, bits)])

    def test_high_rate_frames_are_drained_without_timer_delay(self):
        CaptureDiagnostics, _ = self._types()
        captured = []
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = CaptureDiagnostics(
                directory, frame_sink=lambda timestamp, bits: captured.append(bits))
            diagnostics.start()
            bits = bytes([1]) * 288
            for _ in range(300):
                self.assertTrue(diagnostics.record_frame(bits))
            diagnostics.stop(timeout=1.0)

        self.assertEqual(len(captured), 300)


if __name__ == "__main__":
    unittest.main()
