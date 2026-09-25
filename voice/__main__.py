"""python -m voice --worker (private JSON-lines IPC) or --check / --devices."""

import argparse
import asyncio
import json
from pathlib import Path
import sys
import threading

from dotenv import load_dotenv

from voice.settings import VoiceSettings


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def check_dependencies():
    import pipecat
    import sounddevice
    from voice.aec import AECDuplexAudio
    AECDuplexAudio()
    import nltk
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError as exc:
        raise ValueError("请先运行 python -m nltk.downloader punkt_tab 安装 Pipecat 启动数据，避免运行时下载。") from exc


async def run_worker(settings):
    import aiohttp
    import sounddevice as sd
    from pipecat.frames.frames import InputAudioRawFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineWorker, PipelineParams
    from pipecat.workers.runner import WorkerRunner
    from voice.aec import AECDuplexAudio
    from voice.echo import PlaybackEchoGuard
    from voice.clients import ASRClient, TTSClient
    from voice.pipeline import SpeechASRProcessor, VoiceCommandProcessor, SpeechTTSProcessor, SpeakerProcessor, SpeakFrame

    loop = asyncio.get_running_loop()
    stopped, ready = asyncio.Event(), asyncio.Event()
    commands = asyncio.Queue(maxsize=100)

    def input_line(line):
        if commands.full():
            stopped.set()
        else:
            commands.put_nowait(line)

    def read_stdin():
        for line in sys.stdin:
            try:
                loop.call_soon_threadsafe(input_line, line)
            except RuntimeError:
                return
        try:
            loop.call_soon_threadsafe(stopped.set)
        except RuntimeError:
            pass

    def event(value):
        if value["type"] == "ready":
            value = {**value, "aec": "WebRTC AEC3"}
        emit(value)
        if value["type"] == "ready":
            microphone.activate()
            ready.set()

    def fail(exc):
        emit({"type": "error", "message": "语音识别连接失败或中断，请检查语音 API Key、资源权限和网络后重新开启。"})
        stopped.set()

    microphone = speaker = AECDuplexAudio()
    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        asr = SpeechASRProcessor(ASRClient(session, settings), event, fail)
        echo_guard = PlaybackEchoGuard()
        router = VoiceCommandProcessor(event, echo_guard)
        tts = SpeechTTSProcessor(TTSClient(session, settings), event)
        worker = PipelineWorker(
            Pipeline([asr, router, tts, SpeakerProcessor(speaker, echo_guard)]),
            params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
            enable_rtvi=False, enable_turn_tracking=False, idle_timeout_secs=None,
        )

        async def capture():
            await ready.wait()
            while not stopped.is_set():
                chunk = microphone.read()
                if chunk:
                    await worker.queue_frame(InputAudioRawFrame(audio=chunk, sample_rate=16000, num_channels=1))
                else:
                    await asyncio.sleep(0.005)

        async def responses():
            while not stopped.is_set():
                line = await commands.get()
                value = json.loads(line)
                if value.get("type") == "stop":
                    stopped.set()
                elif value.get("type") == "speak" and value.get("text"):
                    await worker.queue_frame(SpeakFrame(value["text"][:1500], value["turn"]))

        # One clock and paired ADC/DAC timestamps for acoustic echo cancellation.
        with sd.RawStream(samplerate=24000, channels=(1, 1), dtype="int16", blocksize=240,
                          device=(settings.input_device, settings.output_device),
                          callback=microphone.callback):
            threading.Thread(target=read_stdin, daemon=True).start()
            runner = WorkerRunner(handle_sigint=False)
            await runner.add_workers(worker)
            tasks = [asyncio.create_task(runner.run()), asyncio.create_task(capture()),
                     asyncio.create_task(responses()), asyncio.create_task(stopped.wait())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                await worker.cancel()
                for task in tasks[1:]:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await asr.client.close()


def main():
    parser = argparse.ArgumentParser(description="Iron_Jump 豆包语音")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--check", action="store_true", help="检查本地配置，不发送网络请求")
    parser.add_argument("--devices", action="store_true", help="列出音频设备")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    try:
        if args.devices:
            import sounddevice as sd
            print(sd.query_devices())
            return 0
        settings = VoiceSettings.from_env()
        if args.check:
            check_dependencies()
            print("语音配置和依赖已就绪；尚未验证云端权限、麦克风和扬声器。")
        elif args.worker:
            check_dependencies()
            asyncio.run(run_worker(settings))
        else:
            parser.print_help()
        return 0
    except ValueError as exc:
        emit({"type": "error", "message": str(exc)})
    except ImportError:
        emit({"type": "error", "message": "语音依赖缺失，请安装 requirements-voice.txt。"})
    except Exception:
        emit({"type": "error", "message": "语音启动失败，请检查音频设备、麦克风权限、网络和语音凭证。"})
    return 1


if __name__ == "__main__":
    sys.exit(main())
