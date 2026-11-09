"""Credential capture (ADR 0005, issue #58).

Customers type their date of birth and SSN digits into the chat. `capture` pulls credential-shaped
text out and masks it, so only the masked turn reaches the transcript, a model, a checkpoint or a
trace. The candidates go to `identity_gate` through the per-turn context and nowhere else.

Pattern-based, and deliberately greedy: masking something that was not a credential costs a
retry, while missing one leaks a restricted value (GR-09).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

DOB_MASK = "[DOB]"
SSN4_MASK = "[SSN-4]"

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
_MONTH = "(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(?P<d>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?P<y>(?:19|20)\d{2})"

_DATE_PATTERNS = [
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),  # 1958-03-14
    re.compile(r"\b(?P<m>\d{1,2})[/-](?P<d>\d{1,2})[/-](?P<y>\d{4})\b"),  # 03/14/1958
    re.compile(rf"\b{_MONTH}\s+{_DAY},?\s+{_YEAR}\b", re.IGNORECASE),  # March 14, 1958
    re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH},?\s+{_YEAR}\b", re.IGNORECASE),  # 14 Mar 1958
]
_FULL_SSN = re.compile(r"\b\d{3}[- ]?\d{2}[- ]?(?P<last4>\d{4})\b")
_SSN_CONTEXT = re.compile(r"\b(ssn|social|last[\s-]*(four|4)|ends?\s+in)\b", re.IGNORECASE)
_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_WORD = "(?:" + "|".join(_DIGIT_WORDS) + ")"
# Four or more digit words: "last four seven eight two three" keeps the last four of the run.
_SPELLED_RUN = re.compile(rf"\b{_WORD}(?:[\s,-]+{_WORD}){{3,}}\b", re.IGNORECASE)
_FOUR_DIGITS = re.compile(r"\b\d{4}\b")


@dataclass(frozen=True)
class Credentials:
    """Candidates from one turn. Never printed: `repr` shows only which values are present."""

    dob: date | None = field(default=None, repr=False)
    last4: str | None = field(default=None, repr=False)

    @property
    def complete(self) -> bool:
        return self.dob is not None and self.last4 is not None

    def __repr__(self) -> str:
        dob = "<masked>" if self.dob else None
        last4 = "<masked>" if self.last4 else None
        return f"Credentials(dob={dob}, last4={last4})"

    __str__ = __repr__


def _to_date(m: re.Match[str]) -> date | None:
    g = m.groupdict()
    month = _MONTHS[g["mon"].lower()] if g.get("mon") else int(g["m"])
    try:
        return date(int(g["y"]), month, int(g["d"]))
    except ValueError:
        return None


def _sub(pattern: re.Pattern[str], text: str, fn: Callable[[re.Match[str]], str]) -> str:
    return pattern.sub(fn, text)


def capture(text: str) -> tuple[str, Credentials | None]:
    """Return the masked text and the candidates found (None when there are none)."""
    dobs: list[date] = []
    last4s: list[str] = []

    def full_ssn(m: re.Match[str]) -> str:
        last4s.append(m.group("last4"))
        return SSN4_MASK

    def a_date(m: re.Match[str]) -> str:
        found = _to_date(m)
        if found is None:
            return m.group(0)
        dobs.append(found)
        return DOB_MASK

    masked = text
    if _SSN_CONTEXT.search(text):
        masked = _sub(_FULL_SSN, masked, full_ssn)
    for pattern in _DATE_PATTERNS:
        masked = _sub(pattern, masked, a_date)

    # A bare four-digit group is a last-four candidate only in credential context: an SSN word,
    # or a date of birth in the same turn (BH-B2-01: "Sorry, 1958-03-15 and 7832.").
    if dobs or _SSN_CONTEXT.search(text):

        def spelled(m: re.Match[str]) -> str:
            words = re.split(r"[\s,-]+", m.group(0).lower())
            last4s.append("".join(_DIGIT_WORDS[w] for w in words)[-4:])
            return SSN4_MASK

        def digits(m: re.Match[str]) -> str:
            last4s.append(m.group(0))
            return SSN4_MASK

        masked = _sub(_SPELLED_RUN, masked, spelled)
        masked = _sub(_FOUR_DIGITS, masked, digits)

    if not dobs and not last4s:
        return text, None
    return masked, Credentials(dob=dobs[0] if dobs else None, last4=last4s[0] if last4s else None)


def scrub(text: str) -> str:
    """The second pass for any free text written outside the turn (audit, case packets)."""
    return capture(text)[0]
