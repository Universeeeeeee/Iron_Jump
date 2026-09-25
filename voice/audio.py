"""Bounded PCM queues; the PortAudio callbacks never wait for the network."""

import asyncio
from collections import deque
import threading


class PCMOutput:
    def __init__(self):
        self.buffer = bytearray()
        self.lock = threading.Lock()

    def clear(self):
        with self.lock:
            self.buffer.clear()

    async def write(self, data):
        # Back pressure caps queued output at about half a second.
        for offset in range(0, len(data), 960):
            while True:
                with self.lock:
                    if len(self.buffer) < 24000:
                        self.buffer.extend(data[offset:offset + 960])
                        break
                await asyncio.sleep(0.01)

    def callback(self, outdata, frames, timing, status):
        size = frames * 2
        with self.lock:
            chunk = self.buffer[:size]
            del self.buffer[:size]
        outdata[:] = bytes(chunk).ljust(size, b"\0")


class PCMInput:
    def __init__(self):
        self.chunks = deque(maxlen=50)  # 1 second maximum; fail visibly on overrun
        self.lock = threading.Lock()
        self.overflowed = False
        self.enabled = False

    def activate(self):
        with self.lock:
            self.chunks.clear()
            self.overflowed = False
            self.enabled = True

    def callback(self, indata, frames, timing, status):
        with self.lock:
            if not self.enabled:
                return
            if len(self.chunks) == self.chunks.maxlen or status.input_overflow:
                self.overflowed = True
            self.chunks.append(bytes(indata))

    def read(self):
        with self.lock:
            if self.overflowed:
                raise RuntimeError("麦克风音频积压，请检查网络后重新开启语音")
            return self.chunks.popleft() if self.chunks else None
