"""Deterministic rules engine (design doc Section 6). Pure functions, no I/O.

The LLM never decides anything here. Input is the raw recent readings for one child
(never the aggregates, Section 18.5); output is the set of rules that currently hold,
plus which rules could be evaluated at all. A rule that couldn't be evaluated (for
example, value rules while the sensor is silent) is neither opened nor resolved, so
silence is never mistaken for "fine" (Section 2.3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sugarscout.settings import Settings

URGENT = "urgent"
WARNING = "warning"

VALUE_RULES = ("urgent_low", "low", "high", "rapid_drop")
READING_RULES = (*VALUE_RULES, "data_gap")


@dataclass(frozen=True)
class Reading:
    ts: datetime
    value: int


@dataclass(frozen=True)
class RulesConfig:
    urgent_low: int = 54
    low: int = 70
    low_consecutive: int = 2
    high: int = 250
    high_consecutive: int = 4
    rapid_drop_mg_dl: int = 25
    rapid_drop_window: int = 4
    data_gap_seconds: int = 30

    @classmethod
    def from_settings(cls, s: Settings) -> RulesConfig:
        return cls(
            urgent_low=s.rule_urgent_low,
            low=s.rule_low,
            low_consecutive=s.rule_low_consecutive,
            high=s.rule_high,
            high_consecutive=s.rule_high_consecutive,
            rapid_drop_mg_dl=s.rule_rapid_drop_mg_dl,
            rapid_drop_window=s.rule_rapid_drop_window,
            data_gap_seconds=s.rule_data_gap_seconds,
        )


@dataclass(frozen=True)
class RuleHit:
    rule_type: str
    severity: str
    message: str
    trigger_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Evaluation:
    hits: list[RuleHit]
    evaluated: frozenset[str]

    @property
    def hit_types(self) -> frozenset[str]:
        return frozenset(h.rule_type for h in self.hits)


def _evidence(readings: list[Reading], cfg: RulesConfig) -> dict[str, Any]:
    return {
        "readings": [{"ts": r.ts.isoformat(), "value_mg_dl": r.value} for r in readings],
        "config": asdict(cfg),
    }


def evaluate(
    readings: list[Reading], now: datetime, cfg: RulesConfig, child_name: str
) -> Evaluation:
    """`readings` are the child's recent raw readings, oldest first."""
    hits: list[RuleHit] = []
    evaluated: set[str] = {"data_gap"}

    latest = readings[-1] if readings else None
    gap_s = (now - latest.ts).total_seconds() if latest else None

    if latest is None or (gap_s is not None and gap_s >= cfg.data_gap_seconds):
        hits.append(
            RuleHit(
                "data_gap",
                WARNING,
                f"No glucose data from {child_name}'s sensor for "
                f"{'a while' if gap_s is None else f'{int(gap_s)} seconds'}.",
                {
                    "last_reading_at": latest.ts.isoformat() if latest else None,
                    "gap_seconds": gap_s,
                    "config": asdict(cfg),
                },
            )
        )
        # Value rules can't be assessed on stale data: leave their alerts as they are.
        return Evaluation(hits, frozenset(evaluated))

    assert latest is not None
    evaluated.update(VALUE_RULES)

    if latest.value < cfg.urgent_low:
        hits.append(
            RuleHit(
                "urgent_low",
                URGENT,
                f"{child_name}'s glucose is urgently low ({latest.value} mg/dL).",
                _evidence(readings[-1:], cfg),
            )
        )

    tail = readings[-cfg.low_consecutive :]
    if len(tail) == cfg.low_consecutive and all(r.value < cfg.low for r in tail):
        hits.append(
            RuleHit(
                "low",
                WARNING,
                f"{child_name}'s glucose is low ({latest.value} mg/dL).",
                _evidence(tail, cfg),
            )
        )

    tail = readings[-cfg.high_consecutive :]
    if len(tail) == cfg.high_consecutive and all(r.value > cfg.high for r in tail):
        hits.append(
            RuleHit(
                "high",
                WARNING,
                f"{child_name}'s glucose has stayed high ({latest.value} mg/dL).",
                _evidence(tail, cfg),
            )
        )

    window = readings[-cfg.rapid_drop_window :]
    if len(window) >= 2:
        drop = window[0].value - window[-1].value
        if drop >= cfg.rapid_drop_mg_dl:
            hits.append(
                RuleHit(
                    "rapid_drop",
                    WARNING,
                    f"{child_name}'s glucose is dropping fast ({drop} mg/dL in "
                    f"{len(window) - 1} readings).",
                    {**_evidence(window, cfg), "drop_mg_dl": drop},
                )
            )

    return Evaluation(hits, frozenset(evaluated))
