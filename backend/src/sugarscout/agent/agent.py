"""The Scout agent: decides what to ask the child next and whether the parent should get a
non-urgent heads-up. Rules decide, AI advises:

- Urgent alerts never come from here; they come from the deterministic rules engine.
- Nemotron may only pick a question from the allowed list, word it for a child, and draft
  a heads-up. Guardrails in code enforce every limit; anything outside them is overridden.
- Every decision (inputs, model output, what was applied) is stored for the parent.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.agent.questions import BANK, Eligible, eligible
from sugarscout.agent.situation import Situation, build_situation, real_seconds
from sugarscout.ai.gateway import ChatModel
from sugarscout.ai.safety import check_output
from sugarscout.ai.summary import _PARENT_ADVICE, SummaryRejected, _extract_json
from sugarscout.alerts.service import raise_alert
from sugarscout.log import get_logger
from sugarscout.rules.engine import RuleHit
from sugarscout.settings import Settings

log = get_logger(__name__)

HEADS_UP_COOLDOWN_MIN = 30  # CGM minutes between heads-ups
QUESTION_TTL_MIN = 60  # a question the child ignores expires after this long
MAX_WORDING = 160
MAX_HEADS_UP = 300

SYSTEM_PROMPT = """You are the care coordinator behind Scout, a friendly companion for {name}, a child
with type 1 diabetes. You see the latest facts and decide two things:

1. Which ONE question (if any) Scout should ask {name} now, chosen ONLY from ALLOWED_QUESTIONS.
   Prefer the question that helps get timely help. Re-word it warmly for a child aged {age}:
   one short sentence, no numbers, no medical words, no advice.
2. Whether {name}'s parent should get a NON-URGENT heads-up now (only if concern_level >= 1 and
   it would help them act sooner). Urgent alerts are handled separately by fixed rules, so
   never write as if it is an emergency. Never give dosing or treatment advice. State the
   facts plainly (glucose, trend, food, insulin timing, how {name} feels) in 1-2 sentences.
   Refer to the child as {name} or "they"; never assume he or she.

Return ONLY JSON:
{{"ask": "<question id or null>", "wording": "<child-facing question>",
  "heads_up": {{"send": true|false, "message": "<parent message>"}},
  "reasons": ["<short reason>", "..."]}}"""


@dataclass
class Decision:
    ask: str | None = None
    wording: str | None = None
    heads_up: str | None = None
    reasons: list[str] = field(default_factory=list)
    status: str = "idle"  # ok | overridden | fallback | idle
    overrides: list[str] = field(default_factory=list)
    model_output: dict[str, Any] | None = None


def _child_safe(wording: str) -> bool:
    w = wording.strip()
    return (
        0 < len(w) <= MAX_WORDING
        and check_output(w) is None
        and not re.search(r"\d{2,}|mg/?dl|insulin dose|units?\b", w.lower())
    )


def _parent_safe(message: str) -> bool:
    """Parents get plain facts (numbers, carbs, insulin timing are fine); what's blocked is
    anything that reads like dosing or treatment advice."""
    m = message.strip()
    return 0 < len(m) <= MAX_HEADS_UP and not any(p.search(m.lower()) for p in _PARENT_ADVICE)


def heads_up_allowed(s: Situation) -> bool:
    if s.concern < 1:
        return False
    # Fixed rules already told the parent about this: don't add noise.
    if s.open_alerts:
        return False
    return s.minutes_since_asked.get("__heads_up__", 1e9) >= HEADS_UP_COOLDOWN_MIN


def default_heads_up(s: Situation) -> str:
    facts = "; ".join(s.concern_reasons) or "worth a look"
    return f"{s.child_name}: {facts}."


def apply_guardrails(raw: dict[str, Any] | None, s: Situation, allowed: list[Eligible]) -> Decision:
    """Turn model output into a decision that stays inside the rules."""
    d = Decision(model_output=raw)
    ids = [e.id for e in allowed]
    if raw is None:
        d.status = "fallback"
        if allowed:
            d.ask, d.wording = allowed[0].id, BANK[allowed[0].id].text
        d.reasons = [e.reason for e in allowed[:1]] + s.concern_reasons
        return d

    d.status = "ok"
    ask = raw.get("ask")
    if ask in (None, "null", ""):
        ask = None
    if ask is not None and ask not in ids:
        d.overrides.append(f"question '{ask}' not allowed now")
        ask = ids[0] if ids else None
    if ask is None and ids and allowed[0].priority >= 90:
        d.overrides.append("a safety question must be asked")
        ask = ids[0]
    d.ask = ask
    if ask is not None:
        wording = str(raw.get("wording") or "")
        if not _child_safe(wording):
            if wording:
                d.overrides.append("child wording replaced")
            wording = BANK[ask].text
        d.wording = wording

    hu = raw.get("heads_up") or {}
    if isinstance(hu, dict) and hu.get("send"):
        if not heads_up_allowed(s):
            d.overrides.append("heads-up not allowed now")
        else:
            msg = str(hu.get("message") or "")
            if not _parent_safe(msg):
                d.overrides.append("heads-up wording replaced")
                msg = default_heads_up(s)
            d.heads_up = msg
    d.reasons = [str(r)[:160] for r in (raw.get("reasons") or [])][:5] or s.concern_reasons
    if d.overrides:
        d.status = "overridden"
    return d


async def _ask_model(
    model: ChatModel, settings: Settings, s: Situation, allowed: list[Eligible]
) -> dict[str, Any] | None:
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(name=s.child_name, age=settings.demo_child_age_band),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "facts": s.facts(),
                    "concern_level": s.concern,
                    "heads_up_allowed": heads_up_allowed(s),
                    "ALLOWED_QUESTIONS": [
                        {"id": e.id, "default_wording": BANK[e.id].text, "why_allowed": e.reason}
                        for e in allowed
                    ],
                }
            ),
        },
    ]
    try:
        try:
            raw = await model.complete(
                settings.nemotron_chat_model,
                messages,
                max_tokens=400,
                temperature=0.2,
                json_mode=True,
            )
        except Exception:
            raw = await model.complete(
                settings.nemotron_chat_model, messages, max_tokens=400, temperature=0.2
            )
        parsed = _extract_json(raw)
        return parsed if isinstance(parsed, dict) else None
    except (SummaryRejected, Exception) as exc:
        log.warning("agent.model_error", error=repr(exc))
        return None


async def run_agent(
    engine: AsyncEngine,
    redis: Redis,
    settings: Settings,
    model: ChatModel | None,
    child_id: uuid.UUID,
    now: datetime,
) -> tuple[Decision, list[int]]:
    """One agent step. Returns the decision and any SMS ids to deliver (always empty:
    heads-ups go to the dashboard and push only)."""
    s = await build_situation(engine, settings, child_id, now)
    async with engine.connect() as conn:
        last_heads_up = (
            await conn.execute(
                text(
                    """SELECT max(opened_at) FROM alerts
                       WHERE child_id = :c AND rule_type = 'agent_heads_up'"""
                ),
                {"c": child_id},
            )
        ).scalar_one()
    if last_heads_up is not None:
        s.minutes_since_asked["__heads_up__"] = (
            (now - last_heads_up).total_seconds() / max(1, settings.sim_tick_seconds) * 5
        )

    allowed = eligible(s)
    if not allowed and not heads_up_allowed(s):
        return Decision(), []

    raw = await _ask_model(model, settings, s, allowed) if model is not None else None
    d = apply_guardrails(raw, s, allowed)

    sms: list[int] = []
    async with engine.begin() as conn:
        if d.ask is not None:
            q = BANK[d.ask]
            await conn.execute(
                text(
                    """INSERT INTO agent_questions
                         (child_id, question, wording, options, reasons, meal_id, asked_at, expires_at)
                       VALUES (:c, :q, :w, CAST(:o AS jsonb), CAST(:r AS jsonb), :m, :now, :exp)"""
                ),
                {
                    "c": child_id,
                    "q": q.id,
                    "w": d.wording,
                    "o": json.dumps([{"value": v, "label": label} for v, label in q.options]),
                    "r": json.dumps(d.reasons),
                    "m": s.last_meal_id if q.about_meal else None,
                    "now": now,
                    "exp": now
                    + timedelta(seconds=real_seconds(QUESTION_TTL_MIN, settings.sim_tick_seconds)),
                },
            )
        if d.heads_up is not None:
            _, sms = await raise_alert(
                conn,
                redis,
                settings,
                child_id,
                s.child_name,
                RuleHit(
                    "agent_heads_up",
                    "info",
                    d.heads_up,
                    {"reasons": d.reasons, "concern": s.concern, "facts": s.facts()},
                ),
            )
        await conn.execute(
            text(
                """INSERT INTO agent_decisions
                     (child_id, decided_at, situation, eligible, output, applied, model, status)
                   VALUES (:c, :now, CAST(:s AS jsonb), CAST(:e AS jsonb), CAST(:o AS jsonb),
                           CAST(:a AS jsonb), :m, :st)"""
            ),
            {
                "c": child_id,
                "now": now,
                "s": json.dumps({**s.facts(), "concern": s.concern}),
                "e": json.dumps([e.__dict__ for e in allowed]),
                "o": json.dumps(d.model_output) if d.model_output is not None else None,
                "a": json.dumps(
                    {
                        "ask": d.ask,
                        "wording": d.wording,
                        "heads_up": d.heads_up,
                        "overrides": d.overrides,
                    }
                ),
                "m": settings.nemotron_chat_model if model is not None else None,
                "st": d.status,
            },
        )
    log.info(
        "agent.decision",
        status=d.status,
        ask=d.ask,
        heads_up=bool(d.heads_up),
        overrides=d.overrides,
    )
    return d, sms
