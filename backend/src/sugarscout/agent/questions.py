"""The fixed question bank and when each question may be asked.

The AI may only choose from questions this module says are allowed right now, so the
child is never asked anything unexpected and never asked too often.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sugarscout.agent.situation import Situation

MOOD_OPTIONS = [
    ("1", "Sad"),
    ("2", "Disappointed"),
    ("3", "Normal"),
    ("4", "Peaceful"),
    ("5", "Happy"),
]


@dataclass(frozen=True)
class Question:
    id: str
    text: str  # default child-facing wording
    options: list[tuple[str, str]]  # (value, label)
    cooldown_min: float  # CGM minutes before the same question can be asked again
    kind: str = "choice"  # choice | mood
    about_meal: bool = False


BANK: dict[str, Question] = {
    q.id: q
    for q in (
        Question(
            "symptoms_now",
            "How do you feel right now?",
            [
                ("fine", "I feel fine"),
                ("shaky", "Shaky"),
                ("dizzy", "Dizzy"),
                ("tummy", "Tummy hurts"),
            ],
            cooldown_min=30,
        ),
        Question(
            "insulin_with_meal",
            "Did you have your insulin with your snack?",
            [("yes", "Yes"), ("not_yet", "Not yet"), ("dont_know", "I don't know")],
            cooldown_min=45,
            about_meal=True,
        ),
        Question(
            "last_meal",
            "When did you last eat?",
            [
                ("just_now", "Just now"),
                ("hour", "About an hour ago"),
                ("while", "A while ago"),
                ("not_today", "Not today"),
            ],
            cooldown_min=90,
        ),
        Question(
            "after_meal_mood",
            "How do you feel after eating?",
            MOOD_OPTIONS,
            cooldown_min=60,
            kind="mood",
            about_meal=True,
        ),
        Question(
            "daily_mood", "How are you feeling today?", MOOD_OPTIONS, cooldown_min=600, kind="mood"
        ),
    )
}


@dataclass(frozen=True)
class Eligible:
    id: str
    priority: int
    reason: str


def eligible(s: Situation) -> list[Eligible]:
    """Questions that may be asked now, highest priority first."""
    if s.pending_question is not None:
        return []  # one question at a time
    out: list[Eligible] = []

    def add(qid: str, priority: int, reason: str) -> None:
        q = BANK[qid]
        if s.minutes_since_asked.get(qid, 1e9) < q.cooldown_min:
            return
        if q.about_meal and qid in s.answered_for_meal:
            return
        out.append(Eligible(qid, priority, reason))

    g, slope, fc = s.glucose, s.slope_per_5min, s.forecast
    fresh = g is not None and not s.glucose_stale
    meal_min = s.minutes_since_meal

    if fresh and g is not None:
        if (
            g < 80
            or (slope is not None and slope <= -4)
            or (fc is not None and fc < 80 and (slope or 0) < -1)
        ):
            add("symptoms_now", 100, "glucose is low or dropping")
        if (
            meal_min is not None
            and meal_min <= 60
            and s.meal_covered_by_insulin is False
            and ((slope is not None and slope >= 1) or g > 160)
        ):
            add("insulin_with_meal", 90, "rising after a meal with no insulin logged")
        no_recent_meal = meal_min is None or meal_min > 240
        if no_recent_meal and ((slope is not None and abs(slope) >= 3) or g > 200 or g < 90):
            add("last_meal", 70, "glucose is moving and no meal was logged recently")
    if meal_min is not None and 45 <= meal_min <= 120 and not s.after_meal_mood_logged:
        add("after_meal_mood", 60, "checking in after a meal")
    if not s.checkin_today and (slope is None or abs(slope) < 2):
        add("daily_mood", 20, "no mood check-in yet today")
    return sorted(out, key=lambda e: -e.priority)


# ---- Matching a spoken answer to an option ------------------------------------------------

_ALIASES: dict[str, dict[str, list[str]]] = {
    "symptoms_now": {
        "fine": ["fine", "good", "okay", "ok", "great", "alright", "all right"],
        "shaky": ["shaky", "shaking", "jittery", "trembl", "wobbly"],
        "dizzy": ["dizzy", "spinning", "lightheaded", "light headed", "woozy"],
        "tummy": ["tummy", "stomach", "belly", "sick", "nause"],
    },
    "insulin_with_meal": {
        "yes": ["yes", "yeah", "yep", "i did", "already"],
        "not_yet": ["not yet", "no", "nope", "didn't", "did not", "forgot"],
        "dont_know": ["don't know", "dont know", "not sure", "i forget", "maybe"],
    },
    "last_meal": {
        "just_now": ["just now", "just ate", "right now", "a minute"],
        "hour": ["hour"],
        "while": ["while", "long time", "earlier", "this morning"],
        "not_today": ["not today", "haven't", "have not", "didn't eat", "nothing"],
    },
}
_MOOD_ALIASES = {
    "1": ["sad", "really bad", "terrible", "awful", "crying"],
    "2": ["disappointed", "not great", "meh", "bad"],
    "3": ["normal", "okay", "ok", "fine", "alright"],
    "4": ["peaceful", "calm", "good", "relaxed"],
    "5": ["happy", "great", "awesome", "amazing", "excited"],
}


def match_answer(question_id: str, transcript: str) -> str | None:
    """Best option value for a spoken answer, or None if it doesn't clearly match."""
    t = " " + re.sub(r"[^a-z' ]", " ", transcript.lower()) + " "
    aliases = _MOOD_ALIASES if BANK[question_id].kind == "mood" else _ALIASES.get(question_id, {})
    # Prefer the longest matching phrase so "not yet" beats "yes"-like fragments.
    best: tuple[int, str] | None = None
    for value, words in aliases.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}", t) and (best is None or len(w) > best[0]):
                best = (len(w), value)
    return best[1] if best else None
