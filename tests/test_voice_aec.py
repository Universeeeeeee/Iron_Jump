import asyncio
from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np
import pytest

pytest.importorskip("pywebrtc_audio")
from voice.aec import AECDuplexAudio


STATUS = SimpleNamespace(input_overflow=False, output_underflow=False)
TIMING = SimpleNamespace(outputBufferDacTime=10.05, inputBufferAdcTime=10.0)


def test_duplex_references_rendered_audio_and_keeps_history_on_interrupt():
    audio = AECDuplexAudio()
    audio.activate()
    asyncio.run(audio.write(b"\x01\0" * 720))
    output = bytearray(480)
    audio.callback(b"\x02\0" * 240, output, 240, TIMING, STATUS)
    assert audio.pairs[0] == (b"\x02\0" * 240, bytes(output), 50)
    assert bytes(output) == b"\x01\0" * 240
    audio.clear()
    audio.callback(b"\x03\0" * 240, output, 240, TIMING, STATUS)
    assert bytes(output) == bytes(480)
    assert audio.pairs[-1][1] == bytes(480)
    assert len(audio.pairs) == 2  # already captured echo must still be processed
    audio.read()
    assert audio.processed_frames == 1 and audio.delay_ms == 50


def test_capture_inactive_and_overrun_are_explicit():
    audio = AECDuplexAudio()
    out = bytearray(480)
    audio.callback(bytes(480), out, 240, TIMING, STATUS)
    assert audio.read() is None
    audio.activate()
    for _ in range(101):
        audio.callback(bytes(480), out, 240, TIMING, STATUS)
    with pytest.raises(RuntimeError, match="积压"):
        audio.read()


def test_clean_capture_is_streamed_as_16khz_pcm():
    audio = AECDuplexAudio()
    audio.activate()
    out = bytearray(480)
    result = bytearray()
    for _ in range(200):
        audio.callback(bytes(480), out, 240, TIMING, STATUS)
        result.extend(audio.read())
    # Streaming resampler retains only a bounded tail, not an entire response.
    assert 31000 <= len(result) // 2 <= 32000
    # Integer resampling may add one-LSB dither even for digital silence.
    assert np.max(np.abs(np.frombuffer(result, dtype="<i2"))) <= 2


def _wav(name):
    with wave.open(str(Path(__file__).parent / "fixtures" / "voice" / name)) as wav:
        assert wav.getframerate() == 24000
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float)


def test_real_aec_suppresses_delayed_speech_echo_and_preserves_double_talk():
    rate = 24000
    far = np.tile(np.r_[_wav("tts_start.wav"), np.zeros(rate // 2)], 12)
    far = far[:len(far) // 240 * 240]
    speech = _wav("tts_pause.wav")
    near_speech = np.zeros_like(far)
    for start in (rate * 15, rate * 18):
        near_speech[start:start + len(speech)] = speech
    echo = np.zeros_like(far)
    echo[1200:] = far[:-1200] * 0.4  # independently defined 50 ms room path
    aec = AECDuplexAudio().processor
    baseline = AECDuplexAudio().processor
    aec.stream_delay_ms = 50
    cleaned, expected = [], []
    for i in range(0, len(far), 240):
        cleaned.extend(aec.process((echo[i:i+240] + near_speech[i:i+240]).astype("int16"), far[i:i+240].astype("int16")))
        expected.extend(baseline.process(near_speech[i:i+240].astype("int16"), np.zeros(240, dtype="int16")))
    cleaned, expected = np.asarray(cleaned, dtype=float), np.asarray(expected, dtype=float)
    region = slice(rate * 8, rate * 14)
    erle = 10 * np.log10((np.mean(echo[region] ** 2) + 1) / (np.mean(cleaned[region] ** 2) + 1))
    assert erle > 20  # cannot pass by merely labelling AEC as enabled
    region = slice(rate * 15, rate * 20)
    assert np.corrcoef(cleaned[region], expected[region])[0, 1] > 0.75
    gain = np.sqrt(np.mean(cleaned[region] ** 2) / np.mean(expected[region] ** 2))
    assert 0.5 < gain < 1.5  # muting the microphone is not a valid AEC solution
