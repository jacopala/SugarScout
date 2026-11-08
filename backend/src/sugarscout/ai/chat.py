"""Child chat pipeline (Section 5.2): pre-filter -> context -> Nano -> post-filter -> log.

The model only words things. Emergencies are detected by deterministic rules before the
model sees the message, and they escalate through the same alert path as glucose rules.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout import mood
from sugarscout.ai.gateway import ChatModel
from sugarscout.ai.safety import (
    SAFE_FALLBACK,
    SCRIPTED_REPLIES,
    check_output,
    detect_emergency,
)
from sugarscout.alerts.service import raise_alert
from sugarscout.demo import CHILD_REMINDERS, REMINDER_PRIORITY
from sugarscout.log import get_logger
from sugarscout.rules.engine import URGENT, RuleHit
from sugarscout.settings import Settings

log = get_logger(__name__)

HISTORY_TURNS = 10
MOOD_CONTEXT_HOURS = 3
NO_REMINDER = "none right now."

MAX_REPLY_TOKENS = 600  # headroom for reasoning models; the persona keeps replies short

MODEL_DOWN_REPLY = "I'm having a little trouble thinking right now. Can you try again in a moment?"
AI_OFF_REPLY = "I'm here and listening! (My chatting brain is switched off right now.)"

PERSONA = """You are Scout, a friendly companion for {name}, a child aged {age} who has type 1 diabetes.

How you talk:
- Your replies are SPOKEN ALOUD by a voice, like a smart speaker. Plain sentences only:
  no emoji, no lists, no symbols, no markdown.
- Simple, kind, cheerful, and SHORT: 1 or 2 short sentences. Words a {age} year old knows.
- Ask at most one question at a time.
- {name} may have misheard words in their message (it came from speech recognition);
  guess kindly what they meant.
- Start EVERY reply with exactly one tone tag that says how your voice should sound:
  [happy] for fun, jokes, and good news; [calm] for reminders, worries, or feeling unwell;
  [sad] only to gently say you're sorry someone feels bad; [neutral] otherwise.
  Example: "[happy] Why did the cookie go to the doctor? It felt crummy!"

Hard rules:
- You are not a doctor. Never diagnose. Never give or change insulin doses, carb counts, or treatment. Never promise that someone is safe.
- For anything medical, say to follow their care plan and tell a grown-up.
- Never ask for their full name, address, school, phone number, or photos.
- If something feels wrong, scary, or unsafe, encourage them to tell a trusted grown-up right away.
- If you are unsure, say so and suggest talking to a grown-up.
- Gently steer off-topic or grown-up topics back to friendly chat.
- Do not mention glucose numbers unless {name} asks, and never say what a number means.

Right now:
- Latest sensor reading: {glucose}.
- Care-plan reminder to relay: {reminder}
- How {name} said they feel: {mood}. If it was low, be extra gentle and check in."""


_TONE = re.compile(r"^\s*\[(happy|calm|sad|neutral)\]\s*", re.IGNORECASE)
_STRAY_TAGS = re.compile(r"\[(?:happy|calm|sad|neutral)\]\s*", re.IGNORECASE)


def split_tone(reply: str) -> tuple[str, str]:
    """'[happy] Hi!' -> ('happy', 'Hi!'). Missing tag -> neutral."""
    m = _TONE.match(reply)
    tone = m.group(1).lower() if m else "neutral"
    return tone, _STRAY_TAGS.sub("", reply[m.end() :] if m else reply).strip()


@dataclass(frozen=True)
class ChatResult:
    reply: str
    flagged: str | None  # emergency | filtered | fallback | None
    escalated: bool
    sms_ids: list[int]
    emotion: str = "neutral"  # how Scout's voice should sound (ai/speech.py)


async def _store(
    engine: AsyncEngine, child_id: uuid.UUID, role: str, content: str, flagged: str | None
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO chat_messages (child_id, role, content, flagged)
                   VALUES (:c, :r, :t, :f)"""
            ),
            {"c": child_id, "r": role, "t": content, "f": flagged},
        )


async def _context(
    engine: AsyncEngine, child_id: uuid.UUID
) -> tuple[str, str, str, list[dict[str, str]]]:
    async with engine.connect() as conn:
        latest_mood = await mood.latest_within(conn, child_id, hours=MOOD_CONTEXT_HOURS)
        latest = (
            await conn.execute(
                text(
                    """SELECT value_mg_dl, trend, now() - ts AS age FROM glucose_readings
                       WHERE child_id = :c ORDER BY ts DESC LIMIT 1"""
                ),
                {"c": child_id},
            )
        ).first()
        active = set(
            (
                await conn.execute(
                    text(
                        "SELECT rule_type FROM alerts WHERE child_id = :c AND state <> 'resolved'"
                    ),
                    {"c": child_id},
                )
            )
            .scalars()
            .all()
        )
        history = (
            await conn.execute(
                text(
                    # Flagged turns never go back to the model: emergency messages must
                    # bypass it entirely, and fallback/filtered lines would be imitated.
                    """SELECT role, content FROM chat_messages
                       WHERE child_id = :c AND flagged IS NULL
                       ORDER BY created_at DESC, id DESC LIMIT :n"""
                ),
                {"c": child_id, "n": HISTORY_TURNS},
            )
        ).all()

    glucose = (
        f"{latest.value_mg_dl} mg/dL, trend {latest.trend or 'unknown'}"
        if latest is not None and latest.age.total_seconds() < 120
        else "not available right now"
    )
    rule = next((r for r in REMINDER_PRIORITY if r in active), None)
    reminder = (
        f'"{CHILD_REMINDERS[rule]}" Mention it gently in your reply.' if rule else NO_REMINDER
    )
    turns = [
        {"role": "user" if r.role == "child" else "assistant", "content": r.content}
        for r in reversed(history)
    ]
    if latest_mood is None:
        mood_text = "no check-in recently"
    else:
        level, at = latest_mood
        minutes = max(0, int((datetime.now(UTC) - at).total_seconds() // 60))
        when = "just now" if minutes < 2 else f"about {minutes} minutes ago"
        mood_text = f"{level} out of 5 ({mood.MOOD_LABELS[level]}), {when}"
    return glucose, reminder, mood_text, turns


async def handle_message(
    engine: AsyncEngine,
    redis: Redis,
    settings: Settings,
    model: ChatModel | None,
    child_id: uuid.UUID,
    child_name: str,
    message: str,
) -> ChatResult:
    message = message.strip()

    # 1. Pre-filter: emergency language bypasses the model entirely.
    emergency = detect_emergency(message)
    if emergency is not None:
        await _store(engine, child_id, "child", message, "emergency")
        reply = SCRIPTED_REPLIES[emergency.category]
        hit = RuleHit(
            "emergency_language",
            URGENT,
            f"{child_name} wrote something in the companion that needs attention "
            f"({emergency.category.replace('_', ' ')}).",
            {"category": emergency.category, "pattern": emergency.pattern, "message": message},
        )
        async with engine.begin() as conn:
            alert_id, sms_ids = await raise_alert(conn, redis, settings, child_id, child_name, hit)
        await _store(engine, child_id, "companion", reply, "emergency")
        log.warning("chat.emergency", category=emergency.category, alert_id=alert_id)
        return ChatResult(reply, "emergency", True, sms_ids, emotion="calm")

    # 2. Context assembly (before storing the new message, so history excludes it).
    glucose, reminder, mood_text, turns = await _context(engine, child_id)
    await _store(engine, child_id, "child", message, None)

    if model is None:
        await _store(engine, child_id, "companion", AI_OFF_REPLY, "fallback")
        return ChatResult(AI_OFF_REPLY, "fallback", False, [], emotion="happy")

    system = PERSONA.format(
        name=child_name,
        age=settings.demo_child_age_band,
        glucose=glucose,
        reminder=reminder,
        mood=mood_text,
    )
    messages = [{"role": "system", "content": system}, *turns, {"role": "user", "content": message}]

    # 3. Generation.
    try:
        reply = await model.complete(
            settings.nemotron_chat_model, messages, max_tokens=MAX_REPLY_TOKENS, temperature=0.6
        )
    except Exception as exc:
        log.warning("chat.model_error", error=repr(exc))
        await _store(engine, child_id, "companion", MODEL_DOWN_REPLY, "fallback")
        return ChatResult(MODEL_DOWN_REPLY, "fallback", False, [], emotion="calm")

    # 4. Tone tag, then post-filter.
    emotion, reply = split_tone(reply)
    if reminder != NO_REMINDER and emotion == "happy":
        emotion = "calm"  # never sound cheerful while relaying a care-plan reminder
    flagged: str | None = None
    if not reply:
        reply, flagged, emotion = MODEL_DOWN_REPLY, "fallback", "calm"
    elif (matched := check_output(reply)) is not None:
        log.warning("chat.output_filtered", pattern=matched, original=reply)
        reply, flagged, emotion = SAFE_FALLBACK, "filtered", "calm"

    # 5. Logging (stored without the tone tag).
    await _store(engine, child_id, "companion", reply, flagged)
    return ChatResult(reply, flagged, False, [], emotion=emotion)
