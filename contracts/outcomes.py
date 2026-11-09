"""The one outcome code every customer turn ends in (PRD section 6, GR-20)."""

from enum import StrEnum


class Outcome(StrEnum):
    ANSWERED = "ANSWERED"
    EXECUTED = "EXECUTED"
    NO_SOURCE = "NO_SOURCE"
    NOT_PERMITTED = "NOT_PERMITTED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    UNAVAILABLE = "UNAVAILABLE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


# The PRD section 6 failure outcomes: the turn did not complete the request.
FAILURE_OUTCOMES = frozenset(
    {
        Outcome.NO_SOURCE,
        Outcome.NOT_PERMITTED,
        Outcome.NEEDS_HUMAN,
        Outcome.UNAVAILABLE,
        Outcome.OUT_OF_SCOPE,
    }
)
