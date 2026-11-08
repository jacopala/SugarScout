"""Voice turns for the Scout display.

The browser cuts speech into short clips and posts each one here. Only clips that
start with the wake phrase ("Hey Scout"), or that follow one while Scout is awake,
reach the chat pipeline; everything else is dropped without being stored or returned.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from sugarscout.ai.chat import handle_message
from sugarscout.ai.speech import Emotion, speak, wav_to_pcm16k
from sugarscout.ai.wake import parse_wake
from sugarscout.api.deps import DemoKey, EngineDep, RedisDep, SettingsDep, enqueue
from sugarscout.demo import DEMO_CHILD_ID
from sugarscout.log import get_logger

router = APIRouter(prefix="/voice", tags=["voice"])
log = get_logger(__name__)

MAX_CLIP_BYTES = 1_000_000  # ~30 s of 16 kHz mono; the browser caps clips at 8 s
AWAKE_WINDOW_S = 8
LISTENING_REPLY = "I'm listening!"


class VoiceTurnOut(BaseModel):
    heard: bool  # False: no wake phrase while asleep, clip ignored
    woke: bool
    awake_for_s: int = 0
    transcript: str | None = None
    reply: str | None = None
    flagged: str | None = None
    escalated: bool = False
    audio: str | None = None  # base64 WAV; None means "use the browser's voice"
    emotion: str = "neutral"


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    emotion: Emotion = "neutral"


class SpeakOut(BaseModel):
    audio: str | None


@router.post("/turn", response_model=VoiceTurnOut, dependencies=[DemoKey])
async def turn(
    request: Request,
    engine: EngineDep,
    redis: RedisDep,
    settings: SettingsDep,
    awake: Annotated[bool, Query()] = False,
) -> VoiceTurnOut:
    speech = request.app.state.speech
    if speech is None:
        raise HTTPException(503, "Voice is unavailable")

    body = await request.body()
    if len(body) > MAX_CLIP_BYTES:
        raise HTTPException(413, "Clip too long")
    try:
        pcm = wav_to_pcm16k(body)
    except Exception as exc:
        raise HTTPException(400, f"Bad audio: {exc}") from exc

    try:
        transcript = await speech.transcribe(pcm)
    except Exception as exc:
        log.warning("voice.asr_failed", error=repr(exc))
        raise HTTPException(502, "Speech recognition failed") from exc

    woke, command = parse_wake(transcript)
    if not woke and not awake:
        return VoiceTurnOut(heard=False, woke=False)

    message = command if woke else transcript.strip()
    if not message:
        if not woke:
            return VoiceTurnOut(heard=False, woke=False)
        # "Hey Scout" on its own: acknowledge and stay awake for the request.
        audio = await speak(speech, redis, settings, LISTENING_REPLY, "happy")
        return VoiceTurnOut(
            heard=True,
            woke=True,
            awake_for_s=AWAKE_WINDOW_S,
            reply=LISTENING_REPLY,
            audio=audio,
            emotion="happy",
        )

    result = await handle_message(
        engine,
        redis,
        settings,
        request.app.state.llm,
        DEMO_CHILD_ID,
        settings.demo_child_name,
        message,
    )
    for nid in result.sms_ids:
        await enqueue(request, "send_sms", nid)
    audio = await speak(speech, redis, settings, result.reply, result.emotion)
    return VoiceTurnOut(
        emotion=result.emotion,
        heard=True,
        woke=woke,
        transcript=message,
        reply=result.reply,
        flagged=result.flagged,
        escalated=result.escalated,
        audio=audio,
    )


@router.post("/speak", response_model=SpeakOut, dependencies=[DemoKey])
async def speak_text(
    body: SpeakIn, request: Request, redis: RedisDep, settings: SettingsDep
) -> SpeakOut:
    return SpeakOut(
        audio=await speak(request.app.state.speech, redis, settings, body.text, body.emotion)
    )
