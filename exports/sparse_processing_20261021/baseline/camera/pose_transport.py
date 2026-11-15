"""Latest-only process handoff that retains invalidation across coalescing."""
from dataclasses import asdict
import threading
from types import SimpleNamespace


class PoseRelay:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest = None
        self._barrier_sequence = 0
        self._barrier = None
        self._stopped = False

    def submit(self, update):
        with self._lock:
            if self._stopped:
                return
            self._latest = update
            if update.status != 'pose':
                self._barrier_sequence += 1
                self._barrier = update
                self._stopped = update.status == 'stopped'

    def packet(self, generation):
        with self._lock:
            update = self._latest
            sequence, barrier = self._barrier_sequence, self._barrier
        if update is None:
            return None
        return {'generation': generation, 'barrier_sequence': sequence,
                'barrier': asdict(barrier) if barrier else None, 'update': asdict(update)}


def decode_update(data):
    def convert(value):
        if isinstance(value, dict):
            return SimpleNamespace(**{key: convert(item) for key, item in value.items()})
        if isinstance(value, list):
            return tuple(convert(item) for item in value)
        return value
    return convert(data)
