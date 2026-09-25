"""Local acoustic probe. Plays a WAV, measures mic energy, never uploads audio."""

import argparse
import asyncio
import json
from pathlib import Path
import time
import wave

import numpy as np
import sounddevice as sd

from voice.aec import AECDuplexAudio


async def probe(path, seconds, input_device=None, output_device=None):
    with wave.open(str(path)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
            raise ValueError("测试音频必须为 24 kHz 单声道 PCM16 WAV")
        pcm = wav.readframes(wav.getnframes())
    if not pcm:
        raise ValueError("测试音频为空")
    audio = AECDuplexAudio()
    raw, clean = [], []
    started = time.monotonic()

    def callback(indata, outdata, frames, timing, status):
        audio.callback(indata, outdata, frames, timing, status)
        if audio.enabled and time.monotonic() - started >= 3:
            raw.append(bytes(indata))

    async def playback():
        while True:
            await audio.write(pcm + bytes(24000))  # half-second gap

    with sd.RawStream(samplerate=24000, blocksize=240, channels=(1, 1), dtype="int16",
                      device=(input_device, output_device), callback=callback):
        await asyncio.sleep(0.2)  # allow the device to prime before measuring
        audio.activate()
        started = time.monotonic()
        writer = asyncio.create_task(playback())
        try:
            while time.monotonic() - started < seconds:
                chunk = audio.read()
                if chunk and time.monotonic() - started >= 3:
                    clean.append(chunk)
                if chunk is None:
                    await asyncio.sleep(0.002)
        finally:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            audio.clear()
    def rms(chunks):
        values = np.frombuffer(b"".join(chunks), dtype="<i2").astype(float)
        return float(np.sqrt(np.mean(values ** 2))) if values.size else 0.0
    before, after = rms(raw), rms(clean)
    return {"aec": "WebRTC AEC3", "processed_frames": audio.processed_frames,
            "device_delay_ms": audio.delay_ms, "raw_mic_rms": round(before, 2),
            "clean_mic_rms": round(after, 2),
            "energy_reduction_db": round(20 * np.log10((before + 1e-9) / (after + 1e-9)), 2),
            "note": "总体能量变化含降噪效果；不能代替真人插话验收。未保存或上传录音。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--seconds", type=int, default=12, choices=range(5, 31))
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)
    args = parser.parse_args()
    try:
        result = asyncio.run(probe(args.wav, args.seconds, args.input_device, args.output_device))
    except Exception as exc:
        print(f"本地 AEC 验证失败（{type(exc).__name__}），请检查 WAV 格式、设备和麦克风权限。")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
