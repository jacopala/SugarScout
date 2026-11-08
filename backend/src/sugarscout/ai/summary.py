"""AI parent summary (Section 5.3).

Numbers are computed here in code; the model only words them. Every item the model
returns must cite the stat keys it is based on, and the whole response is validated:
unparseable JSON, unknown stat keys, or anything resembling treatment advice is
rejected, and the parent sees the computed stats alone.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.gateway import ChatModel
from sugarscout.ai.safety import check_output
from sugarscout.log import get_logger
from sugarscout.settings import Settings

log = get_logger(__name__)

PERIOD_DAYS = 7


async def compute_stats(
    engine: AsyncEngine, child_id: uuid.UUID, days: int = PERIOD_DAYS
) -> dict[str, Any]:
    """Summary statistics from the hourly aggregate plus raw variability (Section 6, Phase 6.1)."""
    async with engine.connect() as conn:
        totals = (
            await conn.execute(
                text(
                    """SELECT sum(n) AS n, sum(sum_mg_dl) AS total,
                              sum(n_urgent_low) AS n_ul, sum(n_low) AS n_l, sum(n_target) AS n_t,
                              sum(n_high) AS n_h, sum(n_very_high) AS n_vh,
                              count(*) FILTER (WHERE n_urgent_low + n_low > 0) AS low_hours
                       FROM glucose_hourly
                       WHERE child_id = :c AND bucket >= now() - make_interval(days => :d)"""
                ),
                {"c": child_id, "d": days},
            )
        ).one()
        spread = (
            await conn.execute(
                text(
                    """SELECT stddev_pop(value_mg_dl) AS sd, avg(value_mg_dl) AS mean
                       FROM glucose_readings
                       WHERE child_id = :c AND ts >= now() - make_interval(days => :d)"""
                ),
                {"c": child_id, "d": days},
            )
        ).one()
        low_hour = (
            await conn.execute(
                text(
                    """SELECT extract(hour FROM bucket)::int AS hr, sum(n_urgent_low + n_low) AS lows
                       FROM glucose_hourly
                       WHERE child_id = :c AND bucket >= now() - make_interval(days => :d)
                       GROUP BY hr HAVING sum(n_urgent_low + n_low) > 0
                       ORDER BY lows DESC LIMIT 1"""
                ),
                {"c": child_id, "d": days},
            )
        ).first()
        daily = (
            await conn.execute(
                text(
                    """SELECT bucket::date AS day, round(avg_mg_dl) AS mean,
                              round(100.0 * n_target / NULLIF(n, 0), 1) AS tir
                       FROM glucose_daily
                       WHERE child_id = :c AND bucket >= now() - make_interval(days => :d)
                       ORDER BY bucket"""
                ),
                {"c": child_id, "d": days},
            )
        ).all()
        chat = (
            await conn.execute(
                text(
                    """SELECT count(*) FILTER (WHERE role = 'child') AS msgs,
                              count(*) FILTER (WHERE role = 'child' AND flagged = 'emergency') AS emerg
                       FROM chat_messages
                       WHERE child_id = :c AND created_at >= now() - make_interval(days => :d)"""
                ),
                {"c": child_id, "d": days},
            )
        ).one()

    n = int(totals.n or 0)

    def pct(x: Any) -> float:
        return round(100.0 * float(x or 0) / n, 1) if n else 0.0

    mean = float(totals.total) / n if n else None
    cv = (
        round(100.0 * float(spread.sd) / float(spread.mean), 1)
        if spread.sd is not None and spread.mean
        else None
    )
    return {
        "period_days": days,
        "readings_count": n,
        "mean_mg_dl": round(mean) if mean is not None else None,
        "time_in_range_pct": pct(totals.n_t),
        "low_pct": pct(totals.n_l),
        "very_low_pct": pct(totals.n_ul),
        "high_pct": pct(totals.n_h),
        "very_high_pct": pct(totals.n_vh),
        "cv_pct": cv,
        "hours_with_lows": int(totals.low_hours or 0),
        "most_common_low_hour_utc": int(low_hour.hr) if low_hour else None,
        "daily": [
            {
                "date": r.day.isoformat(),
                "mean_mg_dl": int(r.mean),
                "time_in_range_pct": float(r.tir or 0),
            }
            for r in daily
        ],
        "child_chat_messages": int(chat.msgs or 0),
        "companion_safety_escalations": int(chat.emerg or 0),
        "range_definitions": {
            "target": "70-180",
            "low": "54-69",
            "very_low": "<54",
            "high": "181-250",
            "very_high": ">250",
        },
    }


class Item(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    stat_keys: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]


class SummaryContent(BaseModel):
    headline: str = Field(min_length=1, max_length=240)
    observations: list[Item] = Field(default_factory=list, max_length=6)
    patterns: list[Item] = Field(default_factory=list, max_length=4)
    wellbeing_notes: list[Item] = Field(default_factory=list, max_length=4)
    discuss_with_care_team: list[str] = Field(default_factory=list, max_length=4)


# Stronger than the chat filter: parent summaries must never read as treatment orders.
_PARENT_ADVICE = [
    re.compile(p)
    for p in (
        r"\b(give|administer|take|inject|adjust|increase|decrease|reduce|change)\b.{0,40}\b(insulin|bolus|basal|dose|units?)\b",
        r"\b(should|must|need to)\b.{0,30}\b(insulin|bolus|basal|dose)\b",
    )
]


class SummaryRejected(ValueError):
    pass


def _extract_json(raw: str) -> Any:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise SummaryRejected("model output contained no JSON object")
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SummaryRejected(f"invalid JSON: {exc}") from exc


def validate_summary(raw: str, stats: dict[str, Any]) -> SummaryContent:
    try:
        content = SummaryContent.model_validate(_extract_json(raw))
    except ValidationError as exc:
        raise SummaryRejected(f"schema: {exc.errors()[0]['msg']}") from exc

    allowed = set(stats)
    texts = [content.headline, *content.discuss_with_care_team]
    for item in [*content.observations, *content.patterns, *content.wellbeing_notes]:
        unknown = [k for k in item.stat_keys if k.split(".")[0].split("[")[0] not in allowed]
        if unknown:
            raise SummaryRejected(f"cites unknown stats: {unknown}")
        texts.append(item.text)

    for t in texts:
        lowered = t.lower()
        if check_output(t) or any(p.search(lowered) for p in _PARENT_ADVICE):
            raise SummaryRejected(f"treatment advice: {t[:120]}")
    return content


SYSTEM_PROMPT = """You write a short weekly summary for the parent of a child with type 1 diabetes.

You are given statistics that were already computed in code. Use ONLY those numbers. Do not
calculate new numbers, and do not invent anything not supported by the statistics.

Never give treatment advice: no insulin, dose, carb-ratio, or therapy changes, and no
diagnosis. Suggestions for the parent must be phrased as things to consider discussing
with the child's care team.

Return ONLY a JSON object with exactly this shape:
{
  "headline": "one plain-language sentence",
  "observations": [{"text": "...", "stat_keys": ["time_in_range_pct"], "confidence": "high"}],
  "patterns": [{"text": "...", "stat_keys": ["daily"], "confidence": "medium"}],
  "wellbeing_notes": [{"text": "...", "stat_keys": ["child_chat_messages"], "confidence": "low"}],
  "discuss_with_care_team": ["..."]
}
Every item's stat_keys must be top-level keys from the statistics you were given.
Keep each text under 200 characters. 2-4 observations, 0-2 patterns, 0-2 wellbeing notes,
1-3 discussion points."""


async def generate_summary(
    engine: AsyncEngine,
    settings: Settings,
    model: ChatModel | None,
    child_id: uuid.UUID,
    child_name: str,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    stats = await compute_stats(engine, child_id)
    status, content, error = "disabled", None, None

    if model is None:
        error = "NVIDIA_API_KEY not set"
    elif stats["readings_count"] == 0:
        status, error = "error", "no readings in period"
    else:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Child's first name: {child_name}\nStatistics (last {PERIOD_DAYS} days):\n"
                + json.dumps(stats, indent=2),
            },
        ]
        try:
            try:
                raw = await model.complete(
                    settings.nemotron_analysis_model,
                    messages,
                    max_tokens=1500,
                    temperature=0.2,
                    json_mode=True,
                )
            except Exception as exc:
                # Some catalog models reject response_format; retry as plain text.
                log.info("summary.json_mode_unsupported", error=repr(exc))
                raw = await model.complete(
                    settings.nemotron_analysis_model, messages, max_tokens=1500, temperature=0.2
                )
            content = validate_summary(raw, stats).model_dump()
            status = "ok"
        except SummaryRejected as exc:
            status, error = "rejected", str(exc)
            log.warning("summary.rejected", reason=error)
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"[:300]
            log.warning("summary.model_error", error=error)

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """INSERT INTO summaries
                         (child_id, period_start, period_end, model, stats, content, status, error)
                       VALUES (:c, :ps, :pe, :m, CAST(:s AS jsonb), CAST(:ct AS jsonb), :st, :e)
                       RETURNING id, created_at"""
                ),
                {
                    "c": child_id,
                    "ps": now - timedelta(days=PERIOD_DAYS),
                    "pe": now,
                    "m": settings.nemotron_analysis_model if model else None,
                    "s": json.dumps(stats),
                    "ct": json.dumps(content) if content else None,
                    "st": status,
                    "e": error,
                },
            )
        ).one()
    return {
        "id": row.id,
        "created_at": row.created_at,
        "model": settings.nemotron_analysis_model if model else None,
        "status": status,
        "error": error,
        "stats": stats,
        "content": content,
    }
