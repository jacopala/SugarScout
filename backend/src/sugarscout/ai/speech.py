"""Speech for the Scout display: NVIDIA Riva ASR (Parakeet) and TTS (Magpie), hosted on
NVIDIA's cloud functions and called over gRPC with the same NVIDIA_API_KEY as the LLMs.

The Riva client is synchronous, so calls run in a worker thread.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
import wave
from typing import Protocol

from redis.asyncio import Redis

from sugarscout.log import get_logger
from sugarscout.settings import Settings

log = get_logger(__name__)

ASR_SAMPLE_RATE = 16_000
TTS_CACHE_TTL_S = 24 * 3600

_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff\U0000fe0f\U0000200d]+"
)
_MARKDOWN = re.compile(r"[*_`#>]+")


def clean_for_speech(text: str) -> str:
    """Strip what a voice shouldn't read aloud: emoji, markdown symbols, extra spaces."""
    t = _EMOJI.sub("", text)
    t = _MARKDOWN.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm16k(data: bytes) -> bytes:
    """Validate the uploaded clip: 16-bit mono PCM WAV at 16 kHz (what the browser sends)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != ASR_SAMPLE_RATE:
            raise ValueError(
                f"expected 16 kHz 16-bit mono WAV, got {w.getframerate()} Hz, "
                f"{w.getsampwidth() * 8}-bit, {w.getnchannels()} channel(s)"
            )
        return w.readframes(w.getnframes())


class SpeechClient(Protocol):
    async def transcribe(self, pcm16k: bytes) -> str: ...

    async def synthesize(self, text: str) -> bytes:
        """Returns a complete WAV file."""
        ...


class RivaSpeech:
    def __init__(self, settings: Settings) -> None:
        import riva.client  # imported lazily: grpc is heavy and tests fake this class

        self._settings = settings
        self._riva = riva.client

        def auth(function_id: str) -> riva.client.Auth:
            return riva.client.Auth(
                uri=settings.riva_server,
                use_ssl=True,
                metadata_args=[
                    ["function-id", function_id],
                    ["authorization", f"Bearer {settings.nvidia_api_key}"],
                ],
            )

        self._asr = riva.client.ASRService(auth(settings.riva_asr_function_id))
        self._tts = riva.client.SpeechSynthesisService(auth(settings.riva_tts_function_id))
        self._asr_config = riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=ASR_SAMPLE_RATE,
            language_code="en-US",
            max_alternatives=1,
            enable_automatic_punctuation=True,
            audio_channel_count=1,
        )

    async def transcribe(self, pcm16k: bytes) -> str:
        def run() -> str:
            resp = self._asr.offline_recognize(pcm16k, self._asr_config)
            return " ".join(
                r.alternatives[0].transcript.strip() for r in resp.results if r.alternatives
            ).strip()

        return await asyncio.wait_for(asyncio.to_thread(run), timeout=self._settings.llm_timeout_s)

    async def synthesize(self, text: str) -> bytes:
        rate = self._settings.riva_tts_sample_rate

        def run() -> bytes:
            resp = self._tts.synthesize(
                text,
                voice_name=self._settings.riva_tts_voice,
                language_code="en-US",
                sample_rate_hz=rate,
            )
            return pcm_to_wav(resp.audio, rate)

        return await asyncio.wait_for(asyncio.to_thread(run), timeout=self._settings.llm_timeout_s)


def get_speech(settings: Settings) -> SpeechClient | None:
    if not (settings.voice_enabled and settings.llm_configured):
        return None
    try:
        return RivaSpeech(settings)
    except Exception as exc:
        log.warning("speech.unavailable", error=repr(exc))
        return None


async def speak(
    speech: SpeechClient | None, redis: Redis, settings: Settings, text: str
) -> str | None:
    """Base64 WAV for `text`, or None if speech is unavailable (the browser then falls
    back to its own voice). Repeated lines come from a Redis cache."""
    spoken = clean_for_speech(text)
    if speech is None or not spoken:
        return None
    key = "tts:" + hashlib.sha256(f"{settings.riva_tts_voice}|{spoken}".encode()).hexdigest()
    try:
        cached = await redis.get(key)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else str(cached)
    except Exception:
        cached = None
    try:
        audio = base64.b64encode(await speech.synthesize(spoken)).decode()
    except Exception as exc:
        log.warning("speech.tts_failed", error=repr(exc))
        return None
    try:
        await redis.set(key, audio, ex=TTS_CACHE_TTL_S)
    except Exception as exc:
        log.info("speech.cache_write_failed", error=repr(exc))
    return audio
