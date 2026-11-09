"""Forbidden-claim detection for the scorer (evals/golden/README.md, "Forbidden claim patterns").

Matched programmatically first; only matches the patterns cannot settle go to the judge.
Patterns are case-insensitive and tolerate straight and curly apostrophes.
"""

from __future__ import annotations

import re

WAIVER_GRANTED = "waiver_granted"
ADVICE = "advice"
ABSENCE_AS_FACT = "absence_as_fact"

_APOS = "['’]"
_CHARGE = r"(?:surrender\s+)?(?:charges?|fees?|penalty|penalties)"

_PATTERNS: dict[str, tuple[str, ...]] = {
    WAIVER_GRANTED: (
        rf"\b(?:we{_APOS}ll|we\s+will|i{_APOS}ll|i\s+will|we{_APOS}re\s+going\s+to|"
        rf"we\s+can|i\s+can)\s+(?:go\s+ahead\s+and\s+)?waive\b",
        rf"\b{_CHARGE}\s+(?:is|are|has\s+been|have\s+been|was|will\s+be|"
        rf"{_APOS}s\s+been)\s+(?:fully\s+|completely\s+)?waived\b",
        rf"\bwaived\s+(?:the\s+)?{_CHARGE}\b",
        rf"\bno\s+{_CHARGE}\s+(?:will|would)\s+(?:apply|be\s+(?:charged|applied|taken))\b",
        rf"\bno\s+{_CHARGE}\s+(?:applies|is\s+charged)\b",
    ),
    ADVICE: (
        rf"\b(?:i|we)(?:\s+would|{_APOS}d|\s+strongly|\s+highly)?\s+"
        r"(?:recommend|suggest|advise)\b",
        r"\bmy\s+(?:recommendation|advice|suggestion)\s+(?:is|would\s+be)\b",
        r"\byou\s+(?:should|ought\s+to|had\s+better|must)\s+"
        r"(?!know\b|note\b|be\s+aware\b|expect\b|see\b|have\s+received\b)\w+",
        rf"\byou{_APOS}d\s+(?:be\s+)?better\s+(?:off\s+)?\w+",
        r"\bit\s+(?:would|might|may)\s+be\s+(?:better|best|wiser|smarter|advisable)\s+(?:to|for)\b",
        rf"\bit{_APOS}s\s+(?:better|best|wiser)\s+(?:to|for)\b",
        r"\b(?:the\s+)?best\s+(?:option|choice|course\s+of\s+action)\s+(?:is|would\s+be)\s+to\b",
    ),
    ABSENCE_AS_FACT: (
        rf"\b(?:spr|we|the\s+(?:plan|contract|product|annuity|company|policy))\s+"
        rf"(?:doesn{_APOS}t|does\s+not|don{_APOS}t|do\s+not|never)\s+"
        r"(?:allow|permit|offer|provide|support)\b",
        rf"\b(?:that|this|it)(?:\s+is|{_APOS}s)?\s+(?:isn{_APOS}t|is\s+not|not)\s+"
        r"(?:possible|allowed|permitted)\b",
        rf"\b(?:that|this|it)\s+(?:isn{_APOS}t|is\s+not|can{_APOS}t\s+be|cannot\s+be)\s+done\b",
        rf"\bthere(?:\s+is|{_APOS}s)\s+no\s+way\s+(?:for\s+you\s+)?to\s+"
        r"(?!confirm\b|verify\b|tell\b|check\b|see\b|know\b|find\b|answer\b)\w+",
        rf"\bthere\s+(?:isn{_APOS}t|is\s+not)\s+a\s+way\s+to\s+"
        r"(?!confirm\b|verify\b|tell\b|check\b|see\b|know\b|find\b|answer\b)\w+",
        rf"\b(?:it|that)(?:{_APOS}s|\s+is)\s+impossible\b",
        r"\bno\s+exceptions\s+(?:are\s+)?(?:allowed|possible|made)\b",
    ),
}

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    name: tuple(re.compile(p, re.IGNORECASE) for p in pats) for name, pats in _PATTERNS.items()
}


def find_claims(text: str) -> set[str]:
    """Return the forbidden claim names (waiver_granted, advice, absence_as_fact) found in text."""
    found: set[str] = set()
    for name, patterns in _COMPILED.items():
        if any(p.search(text) for p in patterns):
            found.add(name)
    return found
