"""Speech credentials are separate from the existing DeepSeek credentials."""

from dataclasses import dataclass, field
import os
import uuid


@dataclass(frozen=True)
class VoiceSettings:
    asr_key: str = field(repr=False)
    tts_key: str = field(repr=False)
    speaker: str = "zh_female_vv_uranus_bigtts"
    asr_resource: str = "volc.seedasr.sauc.duration"
    tts_resource: str = "seed-tts-2.0"
    input_device: int | None = None
    output_device: int | None = None

    @classmethod
    def from_env(cls):
        shared = os.getenv("VOLC_SPEECH_API_KEY", "").strip()
        asr = os.getenv("VOLC_ASR_API_KEY", shared).strip()
        tts = os.getenv("VOLC_TTS_API_KEY", shared).strip()
        if not asr or not tts:
            raise ValueError("请在 .env 配置 VOLC_SPEECH_API_KEY，或分别配置 VOLC_ASR_API_KEY / VOLC_TTS_API_KEY。")
        return cls(
            asr, tts,
            speaker=os.getenv("VOLC_TTS_SPEAKER", cls.speaker),
            asr_resource=os.getenv("VOLC_ASR_RESOURCE_ID", cls.asr_resource),
            tts_resource=os.getenv("VOLC_TTS_RESOURCE_ID", cls.tts_resource),
            input_device=_device("VOICE_INPUT_DEVICE"),
            output_device=_device("VOICE_OUTPUT_DEVICE"),
        )

    def headers(self, service: str) -> dict:
        return {
            "X-Api-Key": self.asr_key if service == "asr" else self.tts_key,
            "X-Api-Resource-Id": self.asr_resource if service == "asr" else self.tts_resource,
            "X-Api-Request-Id" if service == "asr" else "X-Api-Connect-Id": str(uuid.uuid4()),
        }


def _device(name):
    value = os.getenv(name, "").strip()
    return int(value) if value else None
