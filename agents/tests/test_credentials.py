"""Issue #58: credentials are captured and masked before anything sees the turn (ADR 0005)."""

from datetime import date

import pytest

from agents.guards.credentials import DOB_MASK, SSN4_MASK, Credentials, capture, scrub
from agents.runner import GraphDeskRunner
from agents.testing import ScriptedChatModel
from contracts.messages import Intent, IntentKind
from contracts.tools import Role

from .test_graph import FakeSearch, MemoryAudit

DOB = date(1958, 3, 14)
AS_OF = date(2024, 12, 1)


@pytest.mark.parametrize(
    ("text", "dob", "last4", "masked"),
    [
        # BH-B2-02
        (
            "1958-03-14, and the last four are 7823.",
            DOB,
            "7823",
            f"{DOB_MASK}, and the last four are {SSN4_MASK}.",
        ),
        # BH-B2-01: a date in the turn makes a bare 4-digit group a last-four candidate
        (
            "Sorry, 1958-03-15 and 7832.",
            date(1958, 3, 15),
            "7832",
            f"Sorry, {DOB_MASK} and {SSN4_MASK}.",
        ),
        ("My date of birth is 03/14/1958 and my SSN ends in 7823", DOB, "7823", None),
        ("Born March 14, 1958; last 4 of my social: 7823", DOB, "7823", None),
        ("born 14 Mar 1958, ssn last four 7823", DOB, "7823", None),
        ("my ssn is 123-45-7823 and dob 1958-03-14", DOB, "7823", None),
        ("last four seven eight two three, born 1958-03-14", DOB, "7823", None),
        ("Just my DOB: 1958-03-14", DOB, None, f"Just my DOB: {DOB_MASK}"),
        ("the last four of my SSN are 7823", None, "7823", None),
    ],
)
def test_capture_finds_and_masks_credentials(
    text: str, dob: date | None, last4: str | None, masked: str | None
) -> None:
    out, creds = capture(text, AS_OF)
    assert creds is not None
    assert creds.dob == dob
    assert creds.last4 == last4
    if masked is not None:
        assert out == masked
    assert "7823" not in out and "1958" not in out
    assert "seven" not in out


@pytest.mark.parametrize(
    "text",
    [
        "What's my current balance?",
        "Can I withdraw $5,000 this year?",
        "What is the surrender charge in year 5?",
        "I'd like to take out 2000 dollars",  # an amount, no credential context
    ],
)
def test_text_without_credentials_is_unchanged(text: str) -> None:
    assert capture(text, AS_OF) == (text, None)


def test_an_impossible_date_is_not_a_dob() -> None:
    out, creds = capture("dob 1958-02-30", AS_OF)
    assert creds is None and out == "dob 1958-02-30"


def test_credentials_never_print_their_values() -> None:
    creds = Credentials(dob=DOB, last4="7823")
    for shown in (repr(creds), str(creds), f"{creds}"):
        assert "7823" not in shown and "1958" not in shown
    assert creds.complete
    assert not Credentials(dob=DOB, last4=None).complete


def test_scrub_is_the_masked_text() -> None:
    assert scrub("ssn 7823, born 1958-03-14", AS_OF) == f"ssn {SSN4_MASK}, born {DOB_MASK}"


# ---------- the runner captures before the transcript, models and trace ----------
def test_runner_masks_the_turn_before_anything_sees_it() -> None:
    concierge = ScriptedChatModel([Intent(kind=IntentKind.VERIFY)])
    runner = GraphDeskRunner(
        search=FakeSearch([]),
        audit=MemoryAudit(),
        models={Role.CONCIERGE: concierge, Role.KNOWLEDGE: ScriptedChatModel()},
        clock=lambda: date(2024, 12, 1),
    )
    conv = runner.start("SPR-1001")
    result = runner.send(conv, "My date of birth is 1958-03-14 and the last four are 7823.")

    state = runner._states[conv]
    dumped = state.model_dump_json()
    seen_by_model = " ".join(str(m.content) for call in concierge.calls for m in call)
    for leaked in ("7823", "1958-03-14"):
        assert leaked not in dumped
        assert leaked not in seen_by_model
        assert leaked not in result.model_dump_json()
    assert DOB_MASK in state.transcript[0].text


# ---------- #70: values were reachable through asdict, equality and pickling ----------
# Found by /code-review on PR #64 (standards).
def test_issue_70_credentials_expose_their_values_only_as_attributes() -> None:
    import dataclasses
    import pickle

    a, b = Credentials(dob=DOB, last4="7823"), Credentials(dob=DOB, last4="7823")
    assert not dataclasses.is_dataclass(a)
    with pytest.raises(TypeError):
        dataclasses.asdict(a)  # type: ignore[call-overload]
    assert a != b  # identity, not value: equality cannot be used to probe a guess
    with pytest.raises(TypeError):
        pickle.dumps(a)
    assert not hasattr(a, "__dict__")
    assert (a.dob, a.last4) == (DOB, "7823")


# ---------- #69: ordinary turns were captured and would count as failed challenges ----------
# Found by /code-review on PR #64 (spec). ADR 0005: a misparse must not count as an attempt.
@pytest.mark.parametrize(
    "text",
    [
        "Can I take out 2000 by 12/31/2026?",  # a future date is not a date of birth
        "withdraw 5000 dollars, my social worker said I could",  # "social" alone is not SSN
        "I opened it on 2022-06-01, can I take $2000 out?",  # too recent to be a birth date
    ],
)
def test_issue_69_ordinary_turns_are_not_credentials(text: str) -> None:
    assert capture(text, AS_OF) == (text, None)


def test_issue_69_the_number_next_to_the_ssn_word_wins_and_amounts_stay() -> None:
    out, creds = capture("My last four is 7823 and I want 4000 out", AS_OF)
    assert creds is not None and creds.last4 == "7823"
    assert out == f"My last four is {SSN4_MASK} and I want 4000 out"


def test_issue_69_a_year_is_not_taken_for_the_last_four() -> None:
    out, creds = capture("ssn ends 7823, I was born in 1958", AS_OF)
    assert creds is not None and creds.last4 == "7823"


@pytest.mark.parametrize(
    ("text", "dob", "last4"),
    [
        ("1958-03-14 or wait, 1958-03-15. Last four 7823", None, "7823"),  # two dates
        ("1958-03-14 and 7823, or maybe 7832", DOB, None),  # two bare groups
    ],
)
def test_issue_69_ambiguous_candidates_yield_none(
    text: str, dob: date | None, last4: str | None
) -> None:
    out, creds = capture(text, AS_OF)
    assert creds is not None and (creds.dob, creds.last4) == (dob, last4)
    assert not creds.complete  # asked again, not counted
    for digits in ("7823", "7832", "1958"):
        assert digits not in out


# ---------- #67: a credential sent in its own turn reached the model unmasked ----------
# Found by /code-review on PR #64 (standards). ADR 0005: split across turns must still be masked.
@pytest.mark.parametrize("text", ["7823", "it's 7823", "seven eight two three"])
def test_issue_67_a_bare_last_four_is_captured_while_a_challenge_is_open(text: str) -> None:
    out, creds = capture(text, AS_OF, challenge_open=True)
    assert creds is not None and creds.last4 == "7823"
    assert "7823" not in out and "seven" not in out
    assert capture(text, AS_OF) == (text, None)  # no challenge open: an ordinary number


def test_issue_67_runner_masks_credentials_split_across_turns() -> None:
    concierge = ScriptedChatModel([Intent(kind=IntentKind.VERIFY)] * 2)
    runner = GraphDeskRunner(
        search=FakeSearch([]),
        audit=MemoryAudit(),
        models={Role.CONCIERGE: concierge, Role.KNOWLEDGE: ScriptedChatModel()},
        clock=lambda: AS_OF,
    )
    conv = runner.start("SPR-1001")
    runner.send(conv, "My date of birth is 1958-03-14.")
    runner.send(conv, "7823")
    dumped = runner._states[conv].model_dump_json()
    seen_by_model = " ".join(str(m.content) for call in concierge.calls for m in call)
    for leaked in ("7823", "1958-03-14"):
        assert leaked not in dumped and leaked not in seen_by_model
