"""Non-blocking capture diagnostics and a single-slot display mailbox.

<<<8M-1>> 帧记录大小: 288bit(3节点) → 768bit(8节点×96bit)。
"""
from __future__ import annotations

import csv
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DisplayFrame:
    sequence: int
    nodes: tuple


class LatestFrameMailbox:
    """Keep one newest display frame so a slow GUI can never build a backlog."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sequence = 0
        self._pending: Optional[DisplayFrame] = None

    def publish(self, nodes) -> int:
        frozen = tuple(list(node) for node in nodes)
        with self._lock:
            self._sequence += 1
            self._pending = DisplayFrame(self._sequence, frozen)
            return self._sequence

    def take(self) -> Optional[DisplayFrame]:
        with self._lock:
            pending = self._pending
            self._pending = None
            return pending

    def clear(self) -> None:
        with self._lock:
            self._pending = None


class CaptureDiagnostics:
    """Write raw USB chunks and status events without blocking the receiver."""

    CSV_FIELDS = ("wall_time", "monotonic_ns", "byte_count", "raw_hex")
    FRAME_BIT_COUNT = 768  # <<<8M-1>> 8节点×96bit

    def __init__(self, directory, *, max_csv_bytes=256 * 1024 * 1024,
                 queue_capacity=8192, heartbeat_seconds=1.0, frame_sink=None,
                 frame_batch_sink=None, frame_bit_count=768):
        self.directory = Path(directory)
        self.max_csv_bytes = max(1, int(max_csv_bytes))
        self.heartbeat_seconds = max(0.01, float(heartbeat_seconds))
        capacity = max(1, int(queue_capacity))
        self._raw_queue = queue.Queue(maxsize=capacity)
        self._frame_queue = queue.Queue(maxsize=capacity)
        self._frame_sink = frame_sink
        self._frame_batch_sink = frame_batch_sink
        self.frame_bit_count = frame_bit_count
        self._last_error = ""
        self._status_queue = queue.SimpleQueue()
        self._metrics_lock = threading.Lock()
        self._metrics = {}
        self._dropped_lock = threading.Lock()
        self._dropped_raw_records = 0
        self._dropped_frame_records = 0
        self._started_at = time.perf_counter()
        self._stop = threading.Event()
        self._thread = None
        self._session_id = None
        self._status_path = None
        self._csv_paths = []

    @property
    def dropped_raw_records(self):
        with self._dropped_lock:
            return self._dropped_raw_records

    @property
    def status_path(self):
        return self._status_path

    @property
    def csv_paths(self):
        return tuple(self._csv_paths)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        self._status_path = self.directory / f"status_{self._session_id}.log"
        self._csv_paths = []
        self._started_at = time.perf_counter()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._writer_loop, name="CaptureDiagnosticsWriter", daemon=True)
        self._thread.start()

    def record_raw(self, data: bytes) -> bool:
        if not data:
            return True
        item = (datetime.now().isoformat(timespec="milliseconds"),
                time.monotonic_ns(), bytes(data))
        try:
            self._raw_queue.put_nowait(item)
            return True
        except queue.Full:
            with self._dropped_lock:
                self._dropped_raw_records += 1
            return False

    def record_frame(self, bits: bytes, timestamp=None) -> bool:
        if (not bits or len(bits) % 96 or len(bits) > 255 * 96
                or (self.frame_bit_count is not None and len(bits) != self.frame_bit_count)):
            raise ValueError("Capture frame size does not match the segment layout")
        if timestamp is None:
            timestamp = time.perf_counter() - self._started_at
        try:
            self._frame_queue.put_nowait((float(timestamp), bytes(bits)))
            return True
        except queue.Full:
            with self._dropped_lock:
                self._dropped_frame_records += 1
            return False

    def increment(self, name: str, amount=1) -> None:
        with self._metrics_lock:
            self._metrics[name] = self._metrics.get(name, 0) + amount

    def log_status(self, event: str, **fields) -> None:
        self._status_queue.put((datetime.now().isoformat(timespec="milliseconds"),
                                str(event), dict(fields)))

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def request_stop(self):
        if not self._stop.is_set():
            self.log_status("logger_stopping")
            self._stop.set()

    def stop(self, timeout=5.0):
        self.request_stop()
        if self._thread is not None:
            self._thread.join(timeout)
        return not self.is_running

    def snapshot(self):
        return {**self._heartbeat_fields(), "last_error": self._last_error}

    def _open_csv(self, part):
        path = self.directory / f"raw_{self._session_id}_part{part:03d}.csv"
        stream = path.open("w", encoding="utf-8", newline="", buffering=1024 * 1024)
        writer = csv.DictWriter(stream, fieldnames=self.CSV_FIELDS)
        self._csv_bytes = writer.writeheader()
        stream.flush()
        self._csv_paths.append(path)
        return stream, writer

    @staticmethod
    def _status_line(timestamp, event, fields):
        values = [f"time={timestamp}", f"event={event}"]
        values.extend(f"{key}={value}" for key, value in sorted(fields.items()))
        return " ".join(values) + os.linesep

    def _write_status_pending(self, status_stream):
        while True:
            try:
                item = self._status_queue.get_nowait()
            except queue.Empty:
                return
            status_stream.write(self._status_line(*item))

    def _heartbeat_fields(self):
        with self._metrics_lock:
            fields = dict(self._metrics)
        fields["raw_queue_depth"] = self._raw_queue.qsize()
        fields["frame_queue_depth"] = self._frame_queue.qsize()
        fields["dropped_raw_records"] = self.dropped_raw_records
        fields["dropped_frame_records"] = self._dropped_frame_records
        return fields

    def _writer_loop(self):
        status_stream = csv_stream = None
        try:
            status_stream = self._status_path.open("a", encoding="utf-8", buffering=1)
            csv_stream, csv_writer = self._open_csv(1)
            part = 1
            next_heartbeat = time.monotonic() + self.heartbeat_seconds
            status_stream.write(self._status_line(
                datetime.now().isoformat(timespec="milliseconds"), "logger_started", {}))
            while (not self._stop.is_set() or not self._raw_queue.empty()
                   or not self._frame_queue.empty()):
                self._write_status_pending(status_stream)
                now = time.monotonic()
                if now >= next_heartbeat:
                    status_stream.write(self._status_line(
                        datetime.now().isoformat(timespec="milliseconds"),
                        "heartbeat", self._heartbeat_fields()))
                    next_heartbeat = now + self.heartbeat_seconds
                batch = []
                for _ in range(128):
                    try:
                        batch.append(self._frame_queue.get_nowait())
                    except queue.Empty:
                        break
                if batch:
                    try:
                        if self._frame_batch_sink is not None:
                            self._frame_batch_sink(batch)
                        elif self._frame_sink is not None:
                            for timestamp, bits in batch:
                                self._frame_sink(timestamp, bits)
                        self.increment("accepted_frames", len(batch))
                    except Exception as exc:
                        self._last_error = repr(exc)
                        self.increment("frame_sink_errors", len(batch))
                        self.log_status("frame_sink_error", error=repr(exc))
                for index in range(128):
                    try:
                        wall_time, monotonic_ns, data = self._raw_queue.get(
                            timeout=0.01 if not batch and index == 0 else 0.0)
                    except queue.Empty:
                        break
                    self._csv_bytes += csv_writer.writerow({
                        "wall_time": wall_time, "monotonic_ns": monotonic_ns,
                        "byte_count": len(data), "raw_hex": data.hex(" "),
                    })
                    self.increment("raw_chunks")
                    self.increment("raw_bytes", len(data))
                    # All CSV fields are ASCII; counting written chars avoids tell()
                    # flushing the text buffer on every USB chunk.
                    if self._csv_bytes >= self.max_csv_bytes:
                        csv_stream.close()
                        part += 1
                        csv_stream, csv_writer = self._open_csv(part)
            self._write_status_pending(status_stream)
            status_stream.write(self._status_line(
                datetime.now().isoformat(timespec="milliseconds"),
                "logger_stopped", self._heartbeat_fields()))
        except Exception as exc:
            logging.exception("Capture recorder failed")
            self._last_error = repr(exc)
            self.increment("writer_errors")
        finally:
            for stream in (csv_stream, status_stream):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception as exc:
                        self._last_error = repr(exc)
                        self.increment("writer_errors")
