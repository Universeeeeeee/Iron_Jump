"""Pipecat processors. The Qt business bridge never runs on the audio loop."""

import time
from dataclasses import dataclass

from pipecat.frames.frames import (
    DataFrame, InputAudioRawFrame, OutputAudioRawFrame,
    InterruptionFrame, TranscriptionFrame, InterimTranscriptionFrame,
    StartFrame, CancelFrame, EndFrame,
)
from pipecat.processors.frame_processor import FrameProcessor

from voice.command_router import is_filler, match_command, normalize
from voice.protocol import Utterances, SpeechProtocolError


@dataclass
class SpeakFrame(DataFrame):
    text: str
    turn: int


@dataclass
class SpeechAudioFrame(OutputAudioRawFrame):
    spoken_text: str = ""


class SpeechASRProcessor(FrameProcessor):
    def __init__(self, client, emit, fail):
        super().__init__()
        self.client, self.emit, self.fail = client, emit, fail
        self.buffer = bytearray()
        self.reader = None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            try:
                await self.client.open()
            except Exception as exc:
                self.fail(exc)
                return
            self.reader = self.create_task(self._read())
            self.emit({"type": "ready"})
        elif isinstance(frame, (CancelFrame, EndFrame)):
            if self.reader:
                await self.cancel_task(self.reader)
            await self.client.close()
            await self.push_frame(frame, direction)
        elif isinstance(frame, InputAudioRawFrame):
            self.buffer.extend(frame.audio)
            if len(self.buffer) >= 6400:  # 200 ms, 16 kHz mono PCM16
                try:
                    await self.client.send(bytes(self.buffer))
                    self.buffer.clear()
                except Exception as exc:
                    self.fail(exc)
        else:
            await self.push_frame(frame, direction)

    async def _read(self):
        utterances = Utterances()
        try:
            async for payload in self.client.results():
                for text, final in utterances.extract(payload):
                    cls = TranscriptionFrame if final else InterimTranscriptionFrame
                    await self.push_frame(cls(text=text, user_id="microphone", timestamp=str(time.time())))
            self.fail(SpeechProtocolError("ASR 会话已结束，请重新开启语音"))
        except Exception as exc:
            self.fail(exc)


class VoiceCommandProcessor(FrameProcessor):
    """Interrupt on meaningful recognition; execute only definite utterances."""

    def __init__(self, emit, echo_guard=None):
        super().__init__()
        self.emit = emit
        self.echo_guard = echo_guard
        self.turn = 0
        self.in_utterance = False
        self.pending_partial = ""

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
            final = isinstance(frame, TranscriptionFrame)
            if self.echo_guard and self.echo_guard.is_echo(frame.text, final=final):
                self.pending_partial = ""
                if final:
                    self.in_utterance = False
                return
            if is_filler(frame.text):
                self.pending_partial = ""
                if final:
                    self.in_utterance = False
                return
            if not final and not self.in_utterance and not match_command(frame.text):
                value = normalize(frame.text)
                stable = (len(value) >= 4 and len(self.pending_partial) >= 4
                          and value.startswith(self.pending_partial))
                self.pending_partial = value
                if not stable:
                    self.emit({"type": "transcript", "text": frame.text, "final": False, "turn": self.turn})
                    return
            if not self.in_utterance:
                self.turn += 1
                self.in_utterance = True
                await self.broadcast_interruption()
                self.emit({"type": "turn", "turn": self.turn})
            self.emit({"type": "transcript", "text": frame.text, "final": final, "turn": self.turn})
            if final:
                self.in_utterance = False
                self.pending_partial = ""
        elif isinstance(frame, SpeakFrame):
            if frame.turn == self.turn:
                await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)


class SpeechTTSProcessor(FrameProcessor):
    def __init__(self, client, emit):
        super().__init__()
        self.client, self.emit = client, emit
        self.synthesis = None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame)):
            if self.synthesis:
                await self.cancel_task(self.synthesis)
                self.synthesis = None
            await self.push_frame(frame, direction)
        elif isinstance(frame, SpeakFrame):
            if self.synthesis:
                await self.cancel_task(self.synthesis)
            self.synthesis = self.create_task(self._speak(frame))
        else:
            await self.push_frame(frame, direction)

    async def _speak(self, frame):
        started = time.perf_counter()
        first = True
        try:
            async for chunk in self.client.synthesize(frame.text):
                if first:
                    self.emit({"type": "metric", "name": "tts_first_chunk_ms",
                               "value": round((time.perf_counter() - started) * 1000), "turn": frame.turn})
                    first = False
                await self.push_frame(SpeechAudioFrame(audio=chunk, sample_rate=24000, num_channels=1, spoken_text=frame.text))
        except Exception:
            # Never put headers, keys or provider payloads into the IPC log.
            self.emit({"type": "error", "message": "豆包语音合成失败，请检查网络、音色和 TTS 权限；文字反馈仍然有效。"})


class SpeakerProcessor(FrameProcessor):
    def __init__(self, output, echo_guard=None):
        super().__init__()
        self.output = output
        self.echo_guard = echo_guard

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame)):
            self.output.clear()
        if isinstance(frame, OutputAudioRawFrame):
            if self.echo_guard and isinstance(frame, SpeechAudioFrame):
                self.echo_guard.remember(frame.spoken_text, len(frame.audio) / 48000)
            await self.output.write(frame.audio)
            if self.echo_guard and isinstance(frame, SpeechAudioFrame):
                self.echo_guard.remember(frame.spoken_text, 0)
        else:
            await self.push_frame(frame, direction)
