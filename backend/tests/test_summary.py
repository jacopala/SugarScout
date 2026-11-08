"""AI summary: stats computed in code, model output validated and rejected when unsafe."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.summary import SummaryRejected, compute_stats, generate_summary, validate_summary
from sugarscout.dev.seed import refresh_aggregates, seed
from sugarscout.settings import Settings

STATS = {"time_in_range_pct": 68.0, "low_pct": 4.0, "daily": [], "mean_mg_dl": 142}

GOOD = {
    "headline": "Alex spent about two thirds of the week in range.",
    "observations": [
        {
            "text": "Time in range was 68%.",
            "stat_keys": ["time_in_range_pct"],
            "confidence": "high",
        },
        {"text": "Lows made up 4% of readings.", "stat_keys": ["low_pct"], "confidence": "high"},
    ],
    "patterns": [],
    "wellbeing_notes": [],
    "discuss_with_care_team": ["Whether the afternoon lows are worth reviewing together."],
}


class FakeModel:
    def __init__(self, reply: str, reject_json_mode: bool = False) -> None:
        self.reply = reply
        self.reject_json_mode = reject_json_mode
        self.json_mode_calls = 0

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> str:
        if json_mode:
            self.json_mode_calls += 1
            if self.reject_json_mode:
                raise ValueError("response_format not supported")
        return self.reply


def test_valid_summary_passes() -> None:
    content = validate_summary(json.dumps(GOOD), STATS)
    assert content.observations[0].stat_keys == ["time_in_range_pct"]


def test_json_wrapped_in_prose_is_extracted() -> None:
    assert validate_summary("Here you go:\n" + json.dumps(GOOD) + "\nThanks!", STATS).headline


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda d: d["observations"][0].update(stat_keys=["made_up_stat"]), "unknown stats"),
        (
            lambda d: d["discuss_with_care_team"].append(
                "Increase the lunch insulin dose by 1 unit."
            ),
            "treatment advice",
        ),
        (
            lambda d: d.update(headline="You should give more insulin at dinner."),
            "treatment advice",
        ),
        (lambda d: d["observations"][0].pop("stat_keys"), "schema"),
    ],
)
def test_bad_summaries_are_rejected(mutate, reason: str) -> None:  # type: ignore[no-untyped-def]
    doc = json.loads(json.dumps(GOOD))
    mutate(doc)
    with pytest.raises(SummaryRejected, match=reason):
        validate_summary(json.dumps(doc), STATS)


def test_non_json_is_rejected() -> None:
    with pytest.raises(SummaryRejected, match="no JSON"):
        validate_summary("Alex had a lovely week!", STATS)


@pytest.fixture
async def child(engine: AsyncEngine) -> AsyncIterator[uuid.UUID]:
    cid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO children (id, first_name, age_band) VALUES (:c, 'Alex', '8-10')"),
            {"c": cid},
        )
    await seed(engine, 1, 7, refresh=False, until=datetime.now(UTC) - timedelta(hours=1), ids=[cid])
    await refresh_aggregates(engine)
    yield cid
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM glucose_readings WHERE child_id = :c"), {"c": cid})
        await conn.execute(text("DELETE FROM children WHERE id = :c"), {"c": cid})
    await refresh_aggregates(engine)


async def test_stats_are_computed_in_code(engine: AsyncEngine, child: uuid.UUID) -> None:
    stats = await compute_stats(engine, child)
    assert 1900 <= stats["readings_count"] <= 2020  # ~7 days at 5-minute spacing
    bands = ["time_in_range_pct", "low_pct", "very_low_pct", "high_pct", "very_high_pct"]
    assert abs(sum(stats[k] for k in bands) - 100) < 0.5
    assert 7 <= len(stats["daily"]) <= 8
    assert stats["cv_pct"] is not None


async def test_generate_stores_ok_summary_with_json_mode_fallback(
    engine: AsyncEngine, settings: Settings, child: uuid.UUID
) -> None:
    model = FakeModel(
        json.dumps(GOOD | {"observations": [GOOD["observations"][0]]}), reject_json_mode=True
    )
    result = await generate_summary(engine, settings, model, child, "Alex")
    assert result["status"] == "ok", result["error"]
    assert model.json_mode_calls == 1
    assert result["stats"]["readings_count"] > 0


async def test_generate_rejects_and_keeps_stats(
    engine: AsyncEngine, settings: Settings, child: uuid.UUID
) -> None:
    bad = json.loads(json.dumps(GOOD))
    bad["headline"] = "Increase Alex's insulin dose at dinner."
    result = await generate_summary(engine, settings, FakeModel(json.dumps(bad)), child, "Alex")
    assert result["status"] == "rejected"
    assert result["content"] is None
    assert result["stats"]["time_in_range_pct"] >= 0


async def test_generate_without_model_is_disabled(
    engine: AsyncEngine, settings: Settings, child: uuid.UUID
) -> None:
    result = await generate_summary(engine, settings, None, child, "Alex")
    assert result["status"] == "disabled"
    assert result["stats"]["readings_count"] > 0
