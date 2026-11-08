"""How much concern a child's message carries (deterministic; no model involved).

Emergencies (severe symptoms, self-harm, abuse) are caught earlier by
`safety.detect_emergency` and escalate on their own. This scores everything below
that line, so worried, sad, or unwell messages are never just chatted past:

- each signal has a weight (a feeling, a body symptom, asking for a grown-up);
- intensifiers ("really", "so") add a point, negation ("not sad") cancels a signal;
- body signals weigh more while glucose is low or falling.

Levels drive what the app does:
- mild (1-2): Scout answers gently.
- moderate (3-4): Scout suggests calling their grown-up, and the app shows a call button.
- high (5+): the same, and the parent also gets a non-urgent "worried words" alert.

Like the safety keyword lists, the weights are a hackathon-grade first line; tune
them with the care team.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sugarscout.ai.safety import normalize

MILD, MODERATE, HIGH = 1, 3, 5

# (weight, label shown to the parent, pattern, is a body signal)
_SIGNALS: list[tuple[int, str, str, bool]] = [
    # Feelings
    (2, "worried", r"\b(worried|worry|worrying|nervous|anxious)\b", False),
    (2, "scared", r"\b(scared|afraid|frightened|terrified)\b", False),
    (2, "sad", r"\b(sad|upset|unhappy|miserable)\b", False),
    (2, "crying", r"\b(cry|crying|cried|in tears)\b", False),
    (2, "lonely", r"\b(lonely|all alone|left out|(nobody|no one) (likes|plays with) me)\b", False),
    (
        2,
        "being picked on",
        r"\b(bull(y|ies|ied|ying)|teas(e|es|ed|ing) me|mean to me|laugh(ed|ing) at me|made fun of me)\b",
        False,
    ),
    (1, "angry", r"\b(angry|mad|frustrated)\b", False),
    # Body
    (3, "shaky or dizzy", r"\b(shaky|shaking|dizzy|wobbly|light ?headed)\b", True),
    (
        2,
        "feeling unwell",
        r"\b(sick|unwell|(not|don't) feel(ing)? (well|good|right)|feel(s|ing)? (bad|weird|funny|strange|wrong))\b",
        True,
    ),
    (
        2,
        "in pain",
        r"\b(hurts?|hurting|pain|aches?|aching|sore|(tummy|stomach|belly|head) ?ache)\b",
        True,
    ),
    (2, "throwing up", r"\b(throw(ing)? up|threw up|puk(e|ed|ing)|vomit\w*|nause\w*)\b", True),
    (1, "sweaty or weak", r"\b(sweaty|sweating|weak|exhausted)\b", True),
    (1, "very thirsty", r"\b(so thirsty|really thirsty|super thirsty)\b", True),
    # Reaching for help
    (
        3,
        "asking for a grown-up",
        r"\b((want|need|miss) (my )?(mom|mommy|mum|mummy|mama|dad|daddy|papa|grandma|grandpa|parents?|grown ?up)"
        r"|call (my )?(mom|mommy|mum|mama|dad|daddy|papa|grandma|grandpa|parents?|grown ?up)"
        r"|come (get|pick up|pick) me)\b",
        False,
    ),
    (
        2,
        "asking for help",
        r"\b(help me|i need help|can you help|something('s| is) wrong)\b",
        False,
    ),
]
_COMPILED = [(w, label, re.compile(p), body) for w, label, p, body in _SIGNALS]

_INTENSIFIER = re.compile(r"\b(really|very|so|super|too|so much|a lot)\b")
# "not sad", "isn't scary", "don't feel sick", "never worried": the signal is negated.
_NEGATED_BEFORE = re.compile(r"(\bnot|n't|\bnever|\bno)\s+(\w+\s+)?$")

BODY_LOW_BONUS = 2


@dataclass(frozen=True)
class Concern:
    score: int = 0
    signals: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        if self.score >= HIGH:
            return "high"
        if self.score >= MODERATE:
            return "moderate"
        if self.score >= MILD:
            return "mild"
        return "none"

    @property
    def suggest_call(self) -> bool:
        return self.score >= MODERATE

    @property
    def notify_parent(self) -> bool:
        return self.score >= HIGH


def assess(message: str, *, glucose_low_or_falling: bool = False) -> Concern:
    text = normalize(message)
    score, signals, body_hit = 0, [], False
    for weight, label, pattern, body in _COMPILED:
        for m in pattern.finditer(text):
            # "feel(ing) not good" style phrases carry their own negation; for the
            # rest, a "not"/"don't" just before the word cancels the signal.
            if not m.group(0).startswith(("not ", "don't ")) and _NEGATED_BEFORE.search(
                text[: m.start()]
            ):
                continue
            score += weight
            signals.append(label)
            body_hit = body_hit or body
            break  # each signal counts once per message
    if score and _INTENSIFIER.search(text):
        score += 1
    if body_hit and glucose_low_or_falling:
        score += BODY_LOW_BONUS
        signals.append("while glucose is low or falling")
    return Concern(score, signals)


def from_mood(level: int) -> Concern:
    """The daily check-in: picking the saddest face is worth a call suggestion
    (moods never alert the parent on their own)."""
    if level <= 1:
        return Concern(MODERATE, ["picked the sad face"])
    if level == 2:
        return Concern(MILD, ["picked the disappointed face"])
    return Concern()


CALL_SUGGESTION = "Would you like to call your grown-up? You can tap the call button."
