"""Credential capture (ADR 0005, issue #58).

Customers type their date of birth and SSN digits into the chat. `capture` pulls credential-shaped
text out and masks it, so only the masked turn reaches the transcript, a model, a checkpoint or a
trace. The candidates go to `identity_gate` through the per-turn context and nowhere else.

Pattern-based, and deliberately greedy: masking something that was not a credential costs a
retry, while missing one leaks a restricted value (GR-09).
"""

import re
from datetime import date
from typing import NoReturn

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

# Issue #68 (found by /code-review on PR #64): two-digit years, dotted, year-first slashed and
# compact dates were not captured and reached the model raw.
_DATE_PATTERNS = [
    re.compile(r"\b(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})\b"),  # 1958-03-14, 1958/03/14
    re.compile(r"\b(?P<m>\d{1,2})[/-](?P<d>\d{1,2})[/-](?P<y>\d{4})\b"),  # 03/14/1958
    re.compile(r"\b(?P<m>\d{1,2})[/-](?P<d>\d{1,2})[/-](?P<yy>\d{2})\b"),  # 3/14/58
    re.compile(r"\b(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})\b"),  # 14.03.1958, day first
    re.compile(r"\b(?P<y>(?:19|20)\d{2})(?P<m>[01]\d)(?P<d>[0-3]\d)\b"),  # 19580314
    re.compile(rf"\b{_MONTH}\s+{_DAY},?\s+{_YEAR}\b", re.IGNORECASE),  # March 14, 1958
    re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH},?\s+{_YEAR}\b", re.IGNORECASE),  # 14 Mar 1958
]
_FULL_SSN = re.compile(r"\b\d{3}[- ]?\d{2}[- ]?(?P<last4>\d{4})\b")  # after an SSN word
_SEPARATED_SSN = re.compile(r"\b\d{3}[- ]\d{2}[- ](?P<last4>\d{4})\b")  # #68: with no word too
_BIRTH_WORD = re.compile(r"\b(born|birth|birthday|dob|d\.o\.b)\b", re.IGNORECASE)
_SPACED_DIGITS = re.compile(r"\b\d(?:[ -]\d){3}\b")  # #68: "7 8 2 3"
_BIRTH_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_SSN_WORD = re.compile(r"\b(ssn|social\s+security|last[\s-]*(?:four|4))\b", re.IGNORECASE)
# How far after an SSN word its digits may sit ("the last four of my SSN are 7823").
_NEAR = 40
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
_MONEY = re.compile(r"\$\s*$|^\s*(?:dollars|usd|bucks)\b", re.IGNORECASE)
_YEARLIKE = re.compile(r"^(?:19|20)\d{2}$")


class Credentials:
    """Candidates from one turn, readable only as attributes.

    Issue #70 (found by /code-review on PR #64): as a dataclass, `asdict`, the generated
    equality and pickling all exposed the values. A slotted class with a masked `repr`,
    identity equality and pickling refused leaves `.dob` and `.last4` as the only way in.
    """

    __slots__ = ("dob", "last4")

    def __init__(self, dob: date | None = None, last4: str | None = None) -> None:
        self.dob = dob
        self.last4 = last4

    @property
    def complete(self) -> bool:
        return self.dob is not None and self.last4 is not None

    def __repr__(self) -> str:
        dob = "<masked>" if self.dob else None
        last4 = "<masked>" if self.last4 else None
        return f"Credentials(dob={dob}, last4={last4})"

    def __reduce__(self) -> NoReturn:
        raise TypeError("Credentials cannot be pickled (ADR 0005)")


def _to_dates(m: re.Match[str]) -> list[date]:
    """The dates a match can mean: a two-digit year is tried as 19xx, then 20xx."""
    g = m.groupdict()
    month = _MONTHS[g["mon"].lower()] if g.get("mon") else int(g["m"])
    years = [1900 + int(g["yy"]), 2000 + int(g["yy"])] if g.get("yy") else [int(g["y"])]
    out = []
    for year in years:
        try:
            out.append(date(year, month, int(g["d"])))
        except ValueError:
            continue
    return out


def _plausible_birth_date(d: date, as_of: date) -> bool:
    """Issue #69: only a date 18 to 120 years before the as-of date can be a date of birth, so
    a withdrawal date or a contract date is left alone and never counts as a failed attempt."""
    return date(as_of.year - 120, 1, 1) <= d <= date(as_of.year - 18, as_of.month, 1)


def _one(values: list[str]) -> str | None:
    """Issue #69: two different candidates are ambiguous. None means ask again, uncounted."""
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else None


def capture(text: str, as_of: date, challenge_open: bool = False) -> tuple[str, Credentials | None]:
    """Return the masked text and the candidates found (None when there are none).

    Issue #69 (found by /code-review on PR #64): any date, "social" alone and the first
    four-digit group anywhere used to count, so ordinary withdrawal turns became failed
    challenges. Now a date must be a plausible birth date, the four digits nearest an SSN word
    win, amounts are left alone, and conflicting candidates yield none.
    """
    dobs: list[date] = []
    near: list[str] = []  # digits right after an SSN word: the strongest evidence
    bare: list[str] = []  # other four-digit groups in credential context

    def a_date(m: re.Match[str]) -> str:
        plausible = [d for d in _to_dates(m) if _plausible_birth_date(d, as_of)]
        if not plausible:
            return m.group(0)
        dobs.append(plausible[0])
        return DOB_MASK

    def full_ssn(m: re.Match[str]) -> str:
        near.append(m.group("last4"))
        return SSN4_MASK

    masked = text
    has_ssn_word = bool(_SSN_WORD.search(text))
    masked = _SEPARATED_SSN.sub(full_ssn, masked)
    if has_ssn_word:
        masked = _FULL_SSN.sub(full_ssn, masked)
    for pattern in _DATE_PATTERNS:
        masked = pattern.sub(a_date, masked)

    if has_ssn_word:
        masked = _mask_near_ssn_words(masked, near)
    # A bare four-digit group is a candidate only in credential context: a date of birth in the
    # same turn (BH-B2-01: "Sorry, 1958-03-15 and 7832."), or an SSN word with no digits near it.
    # When the SSN word already found its digits, other numbers are amounts and stay visible.
    # Issue #67 (found by /code-review on PR #64): a reply of just "7823" to the desk's request
    # had no context in its own words and reached the model raw. While a challenge is open,
    # every bare group is a candidate, so credentials split across turns are masked too.
    if challenge_open or dobs or (has_ssn_word and not near):
        masked = _mask_bare_groups(masked, bare)
    else:
        # Issue #75 (found by the red team, #60): spaced and spelled runs were masked only in
        # credential context, so "sorry: 7-8-2-3" after verifying reached the model. Such runs
        # are never an amount or a year, so they are masked in every turn; only plain four-digit
        # groups stay context-dependent, because those can be money.
        masked = _mask_digit_runs(masked, bare)

    if _BIRTH_WORD.search(text):  # #68: a birth year on its own is still part of a DOB
        masked = _BIRTH_YEAR.sub(lambda m: DOB_MASK if _not_money(masked, m) else m[0], masked)

    if not dobs and not near and not bare:
        return masked, None
    if near:
        last4 = _one(near)
    else:
        not_years = [g for g in bare if not _YEARLIKE.match(g)]
        last4 = _one(not_years or bare)
    return masked, Credentials(dob=_one_date(dobs), last4=last4)


def _not_money(text: str, m: re.Match[str]) -> bool:
    before, after = text[max(0, m.start() - 2) : m.start()], text[m.end() : m.end() + 8]
    return not (_MONEY.search(before) or _MONEY.search(after))


def _first_digits(window: str) -> re.Match[str] | None:
    """The earliest digit run in the window, whatever its form (#68: spaced digits too)."""
    hits = [p.search(window) for p in (_SPELLED_RUN, _SPACED_DIGITS, _FOUR_DIGITS)]
    found = [h for h in hits if h is not None]
    return min(found, key=lambda h: h.start()) if found else None


def _one_date(dobs: list[date]) -> date | None:
    return dobs[0] if len(set(dobs)) == 1 else None


def _digits_of(run: str) -> str:
    words = re.split(r"[\s,-]+", run.lower())
    return "".join(_DIGIT_WORDS.get(w, w) for w in words)[-4:]


def _mask_near_ssn_words(text: str, found: list[str]) -> str:
    """Mask the first digit run within _NEAR characters after each SSN word."""
    out, pos = [], 0
    for word in _SSN_WORD.finditer(text):
        if word.start() < pos:
            continue
        window_end = min(word.end() + _NEAR, len(text))
        window = text[word.end() : window_end]
        hit = _first_digits(window)
        if hit is None:
            continue
        found.append(_digits_of(hit.group(0)))
        start, end = word.end() + hit.start(), word.end() + hit.end()
        out.append(text[pos:start] + SSN4_MASK)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _mask_digit_runs(text: str, found: list[str]) -> str:
    """Spelled ("seven eight two three") and spaced ("7 8 2 3") runs: never money, always masked."""

    def run(m: re.Match[str]) -> str:
        found.append(_digits_of(m.group(0)))
        return SSN4_MASK

    text = _SPELLED_RUN.sub(run, text)
    return _SPACED_DIGITS.sub(run, text)


def _mask_bare_groups(text: str, found: list[str]) -> str:
    def digits(m: re.Match[str]) -> str:
        if not _not_money(text, m):
            return m.group(0)  # an amount, not an identifier
        found.append(m.group(0))
        return SSN4_MASK

    text = _mask_digit_runs(text, found)
    return _FOUR_DIGITS.sub(digits, text)


def scrub(text: str, as_of: date) -> str:  # no challenge context: the turn is not live
    """The second pass for any free text written outside the turn (audit, case packets)."""
    return capture(text, as_of)[0]
