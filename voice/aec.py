"""WebRTC AEC3 on paired 10 ms capture/render frames from one duplex stream."""

from collections import deque
import threading

import numpy as np
from pywebrtc_audio import AudioProcessor
import soxr

from voice.audio import PCMOutput


class AECDuplexAudio:
    sample_rate = 24000
    blocksize = 240

    def __init__(self):
        self.output = PCMOutput()
        self.processor = AudioProcessor(
            sample_rate=self.sample_rate, echo_cancellation=True,
            noise_suppression=True, ns_level=1, auto_gain_control=False,
        )
        self.resampler = soxr.ResampleStream(
            self.sample_rate, 16000, 1, dtype="int16", quality="LQ",
        )
        self.pairs = deque(maxlen=100)
        self.lock = threading.Lock()
        self.enabled = False
        self.error = None
        self.processed_frames = 0
        self.delay_ms = 0

    def activate(self):
        with self.lock:
            self.pairs.clear()
            self.error = None
            self.enabled = True

    async def write(self, data):
        await self.output.write(data)

    def clear(self):
        # Drop only audio not yet delivered. Keep AEC history: room echo from
        # samples already rendered persists after the application interrupts.
        self.output.clear()

    def callback(self, indata, outdata, frames, timing, status):
        self.output.callback(outdata, frames, timing, status)
        with self.lock:
            if not self.enabled:
                return
            if frames != self.blocksize or status.input_overflow or status.output_underflow:
                self.error = "音频帧不同步或设备发生欠载，请重新开启语音。"
                return
            if len(self.pairs) == self.pairs.maxlen:
                self.error = "AEC 音频处理积压，请重新开启语音。"
                return
            delay = max(0, round((timing.outputBufferDacTime - timing.inputBufferAdcTime) * 1000))
            # Reference exactly what this callback hands to the device,
            # including zero padding. Never reference unplayed TTS buffers.
            self.pairs.append((bytes(indata), bytes(outdata), delay))

    def read(self):
        # DSP and resampling run on the worker loop, never in the audio callback.
        # All calls into the non-thread-safe processor stay on this one thread.
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            if not self.pairs:
                return None
            near, far, self.delay_ms = self.pairs.popleft()
        self.processor.stream_delay_ms = self.delay_ms
        clean = self.processor.process(
            np.frombuffer(near, dtype="<i2"), np.frombuffer(far, dtype="<i2"),
        )
        self.processed_frames += 1
        return self.resampler.resample_chunk(clean).tobytes()
