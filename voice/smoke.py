"""Opt-in cloud loopback: Doubao TTS -> real-time PCM -> Doubao ASR.

Only synthetic command audio is sent. This does not operate USB equipment.
"""

import argparse
import asyncio
import json
from pathlib import Path
import time
import wave

import aiohttp
from dotenv import load_dotenv
import numpy as np
import soxr

from voice.clients import ASRClient, TTSClient
from voice.command_router import is_filler, match_command
from voice.protocol import Utterances
from voice.settings import VoiceSettings


async def check_phrase(session, settings, phrase, output_dir):
    tts = TTSClient(session, settings)
    started = time.perf_counter()
    first_ms = None
    audio = bytearray()
    async for chunk in tts.synthesize(phrase):
        if first_ms is None:
            first_ms = round((time.perf_counter() - started) * 1000)
        audio.extend(chunk)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_dir / f"{phrase}.wav"), "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(audio)
    samples = np.frombuffer(audio, dtype="<i2").astype(np.float32)
    pcm = np.clip(np.rint(soxr.resample(samples, 24000, 16000)), -32768, 32767).astype("<i2").tobytes()
    client = ASRClient(session, settings)
    utterances, recognized = Utterances(), []
    final_ms = None
    async def collect():
        nonlocal final_ms
        async for payload in client.results():
            for text, final in utterances.extract(payload):
                if final and not is_filler(text):
                    recognized.append(text)
                    final_ms = round((time.perf_counter() - started) * 1000)
    reader = None
    try:
        await client.open()
        started = time.perf_counter()
        reader = asyncio.create_task(collect())
        data = pcm + bytes(16000 * 2)  # trailing silence gives server VAD time to finalize
        for offset in range(0, len(data), 6400):
            await client.send(data[offset:offset + 6400])
            await asyncio.sleep(0.2)
        await client.send(b"", last=True)
        await asyncio.wait_for(reader, 15)
    finally:
        if reader and not reader.done():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        await client.close()
    passed = [match_command(t) for t in recognized] == [match_command(phrase)]
    return {"phrase": phrase, "recognized": recognized, "passed": passed,
            "tts_first_chunk_ms": first_ms, "asr_final_from_audio_start_ms": final_ms}


async def smoke(settings, output_dir=None):
    timeout = aiohttp.ClientTimeout(total=None, connect=10)
    results = []
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for phrase in ("开始测试", "暂停测试", "继续测试", "结束测试"):
            result = await check_phrase(session, settings, phrase, output_dir)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return all(result["passed"] for result in results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="保存合成的 WAV，供人工试听")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    try:
        return 0 if asyncio.run(smoke(VoiceSettings.from_env(), args.output_dir)) else 1
    except ValueError as exc:
        print(str(exc))
    except Exception:
        print("云端语音自检失败；请检查 ASR/TTS 权限、音色、额度和网络。没有操作测试设备。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
