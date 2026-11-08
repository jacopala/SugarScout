"""Rules engine: pure-function tests with synthetic traces (Section 12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sugarscout.rules.engine import Reading, RulesConfig, evaluate

CFG = RulesConfig()
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def trace(*values: int, step_s: int = 5) -> list[Reading]:
    return [Reading(T0 + timedelta(seconds=i * step_s), v) for i, v in enumerate(values)]


def hits(readings: list[Reading], now: datetime | None = None) -> set[str]:
    now = now or (readings[-1].ts + timedelta(seconds=1) if readings else T0)
    return set(evaluate(readings, now, CFG, "Alex").hit_types)


def test_steady_trace_is_quiet() -> None:
    assert hits(trace(118, 121, 119, 122, 120)) == set()


def test_urgent_low_fires_on_a_single_reading_below_54() -> None:
    assert "urgent_low" in hits(trace(80, 60, 53))
    assert "urgent_low" not in hits(trace(80, 60, 54))  # boundary: 54 is not urgent


def test_low_needs_consecutive_readings() -> None:
    assert "low" not in hits(trace(100, 90, 69))
    assert "low" in hits(trace(100, 69, 68))
    assert "low" not in hits(trace(100, 69, 70))  # boundary: 70 is not low


def test_high_needs_a_sustained_run() -> None:
    assert "high" not in hits(trace(240, 260, 270, 280))
    assert "high" in hits(trace(260, 270, 280, 290))
    assert "high" not in hits(trace(260, 270, 250, 290))  # 250 is not above 250


def test_rapid_drop_over_window() -> None:
    assert "rapid_drop" in hits(trace(130, 120, 112, 105))  # 25 over 3 steps
    assert "rapid_drop" not in hits(trace(130, 122, 115, 106))  # 24
    assert "rapid_drop" not in hits(trace(105, 112, 120, 130))  # rising


def test_data_gap_when_sensor_goes_quiet() -> None:
    r = trace(120, 121)
    assert "data_gap" not in hits(r, now=r[-1].ts + timedelta(seconds=29))
    assert "data_gap" in hits(r, now=r[-1].ts + timedelta(seconds=30))


def test_no_readings_at_all_is_a_data_gap_not_fine() -> None:
    ev = evaluate([], T0, CFG, "Alex")
    assert ev.hit_types == {"data_gap"}


def test_stale_data_does_not_evaluate_value_rules() -> None:
    """Silence must never resolve a low: value rules aren't evaluated on stale data."""
    r = trace(60, 50)
    ev = evaluate(r, r[-1].ts + timedelta(minutes=5), CFG, "Alex")
    assert ev.hit_types == {"data_gap"}
    assert ev.evaluated == {"data_gap"}


def test_rapid_drop_into_urgent_low_fires_all_three() -> None:
    assert hits(trace(120, 90, 66, 50)) >= {"rapid_drop", "low", "urgent_low"}


def test_trigger_data_records_readings_and_config() -> None:
    ev = evaluate(trace(80, 50), T0 + timedelta(seconds=6), CFG, "Alex")
    hit = next(h for h in ev.hits if h.rule_type == "urgent_low")
    assert hit.trigger_data["readings"][-1]["value_mg_dl"] == 50
    assert hit.trigger_data["config"]["urgent_low"] == 54
    assert hit.severity == "urgent"


def test_rapid_rise_over_window() -> None:
    assert "rapid_rise" in hits(trace(130, 140, 150, 160))  # 30 over 3 steps
    assert "rapid_rise" not in hits(trace(130, 139, 149, 159))  # 29
    assert "rapid_rise" not in hits(trace(160, 150, 140, 130))  # falling


def test_rapid_rise_message_says_where_glucose_is() -> None:
    ev = evaluate(trace(130, 145, 160, 175), T0 + timedelta(seconds=16), CFG, "Alex")
    hit = next(h for h in ev.hits if h.rule_type == "rapid_rise")
    assert hit.severity == "warning"
    assert "rising fast (45 mg/dL in 3 readings, now 175)" in hit.message
    assert hit.trigger_data["rise_mg_dl"] == 45


def test_high_soon_warns_before_the_high_rule() -> None:
    climb = trace(150, 165, 180, 195, 210, 225, 235)
    got = hits(climb)
    assert "predicted_high" in got
    assert "high" not in got


def test_high_soon_hands_over_to_high() -> None:
    got = hits(trace(200, 220, 240, 255, 265, 275, 285))
    assert "high" in got
    assert "predicted_high" not in got


def test_steady_in_range_has_no_high_soon() -> None:
    assert "predicted_high" not in hits(trace(150, 151, 150, 152, 151, 150, 151))
