"""Deterministic safety filters around the chat model (Sections 2.2, 2.4, 5.2).

- `detect_emergency` runs BEFORE the model. A match means a scripted reply and an
  immediate parent escalation; the model is never called.
- `check_output` runs AFTER the model and replaces anything that looks like medical
  advice, a diagnosis, or a request for identifying details.

Keyword lists are a hackathon-grade first line, tuned for how kids actually write.
A dedicated guard model (e.g. Nemotron content safety) is the production follow-up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def normalize(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"\bcant\b", "can't", t)
    t = re.sub(r"\bdont\b", "don't", t)
    t = re.sub(r"\bim\b", "i'm", t)
    return re.sub(r"\s+", " ", t).strip()


_SYMPTOMS = [
    r"can'?t breathe",
    r"cannot breathe",
    r"hard to breathe",
    r"(really|very|super|so) dizzy",
    r"pass(ing)? out",
    r"\bfaint(ed|ing)?\b",
    r"can'?t see",
    r"\bseizure",
    r"chest (hurts|pain)",
    r"(keep|keeps|can'?t stop) (throwing up|puking|vomiting)",
    r"can'?t (wake|stay awake|think straight)",
    r"\bso confused\b",
]
_SELF_HARM = [
    r"kill (myself|me)",
    r"want to die",
    r"wanna die",
    r"hurt (myself|me on purpose)",
    r"end my life",
    r"don'?t want to (be alive|live)",
    r"\bsuicid",
]
_ABUSE = [
    r"(someone|somebody|he|she|they|my \w+) (hits|hit|hurts|hurt|touched|touches|kicks|kicked) me",
    r"\babus(e|ed|ing)\b",
    r"(scared|afraid) to go home",
]

_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "symptoms": [re.compile(p) for p in _SYMPTOMS],
    "self_harm": [re.compile(p) for p in _SELF_HARM],
    "abuse": [re.compile(p) for p in _ABUSE],
}

SCRIPTED_REPLIES: dict[str, str] = {
    "symptoms": "Thank you for telling me. I've let your grown-up know right now. "
    "Please sit down where you are, and if someone is nearby, tell them how you feel.",
    "self_harm": "I'm really glad you told me. You matter so much. I've let your grown-up "
    "know so they can be with you. Please go find a grown-up you trust right now.",
    "abuse": "Thank you for being brave and telling me. That is not okay, and it is not "
    "your fault. Please talk to a grown-up you trust, like a teacher or a family member.",
}


@dataclass(frozen=True)
class EmergencyMatch:
    category: str
    pattern: str


def detect_emergency(message: str) -> EmergencyMatch | None:
    text = normalize(message)
    for category, patterns in _PATTERNS.items():
        for p in patterns:
            if p.search(text):
                return EmergencyMatch(category, p.pattern)
    return None


_UNSAFE_OUTPUT = [
    # Dosing and treatment changes.
    r"\b\d+(\.\d+)?\s*(units?|u|ml|mg|grams?|g)\b.*\b(insulin|bolus|dose|inject)",
    r"\b(insulin|bolus|dose|inject\w*)\b.*\b\d+(\.\d+)?\s*(units?|u)\b",
    r"\b(increase|decrease|lower|raise|change|skip|double)\b.{0,30}\b(insulin|dose|bolus)\b",
    r"\bcarb ratio\b",
    r"\bcorrection factor\b",
    r"\bdosage\b",
    # Diagnosis.
    r"\byou (have|might have|probably have|may have) (diabetes|dka|ketoacidosis|hypoglycemia|an? \w+ (disease|infection))",
    r"\bdiagnos",
    r"\bi('m| am) (a|your) doctor\b",
    # Identifying details (Section 5.4).
    r"\b(what('s| is)|tell me) your (last name|full name|address|school|phone)",
    r"\bwhere do you live\b",
    r"\b(send|share) (me )?(a |your )?(photo|picture|selfie)",
]
_UNSAFE_RE = [re.compile(p) for p in _UNSAFE_OUTPUT]

SAFE_FALLBACK = (
    "That's a great question for your grown-up or your care team. "
    "Want to tell me something fun about your day?"
)


def check_output(reply: str) -> str | None:
    """Returns the matched pattern if the reply must be replaced, else None."""
    text = normalize(reply)
    for p in _UNSAFE_RE:
        if p.search(text):
            return p.pattern
    return None
