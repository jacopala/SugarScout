"""Wake phrase detection on ASR transcripts: "Hey Scout", "Okay Scout", and the ways
speech recognisers commonly mishear it ("Hey Scott", "hey scoot")."""

from __future__ import annotations

import re

_WAKE = re.compile(
    r"\b(?:hey|hay|hei|heya|hiya|hi|hello|ok|okay|yo)[\s,.!-]*"
    r"(?:scout|scott|scot|scoot|skout|scouts)\b[\s,.!?-]*",
    re.IGNORECASE,
)


# Just the name on its own ("Scout!") also wakes Scout.
_NAME_ONLY = re.compile(r"^\W*(?:scout|scott|scot|scoot|skout)\W*$", re.IGNORECASE)


def parse_wake(transcript: str) -> tuple[bool, str]:
    """Returns (woke, command). The command is whatever follows the wake phrase."""
    if _NAME_ONLY.match(transcript):
        return True, ""
    m = _WAKE.search(transcript)
    if not m:
        return False, ""
    command = transcript[m.end() :].strip(" ,.!?-")
    return True, command
