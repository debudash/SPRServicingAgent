"""Contract tests for the B1 ports (issue #28)."""

import inspect
import re
import typing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue, ValidationError

from contracts.outcomes import Outcome
from contracts.ports import (
    AuditEvent,
    AuditLog,
    AuditRecord,
    DeskRunner,
    KnowledgeChunk,
    KnowledgeSearch,
    TurnResult,
)
from contracts.tools import Node, Step

ARCHITECTURE = Path(__file__).resolve().parents[2] / "docs" / "ARCHITECTURE.md"


def test_every_audit_event_in_the_architecture_exists() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("| `event` |"))
    documented = set(re.findall(r"`([a-z_]+)`", line)) - {"event"}
    assert documented and documented <= {e.value for e in AuditEvent}


def test_audit_record_refuses_an_unknown_event() -> None:
    with pytest.raises(ValidationError):
        AuditRecord(
            audit_id=1,
            conversation_id="CV1",
            turn=1,
            at="2026-11-09T00:00:00Z",
            node=Node.RESPOND,
            event="deleted",
            payload={},
            versions={},
            prev_hash="0",
            row_hash="1",
        )


def test_turn_result_carries_what_the_scorer_reads() -> None:
    r = TurnResult(
        conversation_id="CV1",
        turn=1,
        reply_text="3% in year 5",
        outcome=Outcome.ANSWERED,
        citations=("fee_schedule v1 §Surrender Charges",),
        steps=(Step.SEARCH_KB,),
        nodes=(Node.INTAKE, Node.CONCIERGE, Node.KNOWLEDGE, Node.RESPOND),
    )
    assert r.usage.cost_micros == 0 and not r.provider_error


def test_issue_30_runner_has_no_way_to_skip_the_identity_challenge() -> None:
    # Issue #30 (found by /code-review on PR #29): the old check read positional arguments only,
    # so a keyword-only `gate_b_passed` or a `**kwargs` back door would have passed.
    params = inspect.signature(DeskRunner.start).parameters
    assert list(params) == ["self", "customer_id"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params.values())


# Static conformance: mypy checks these fakes against the Protocols.
class _FakeSearch:
    def search(self, query: str, as_of: date, k: int = 4) -> list[KnowledgeChunk]:
        return []


class _FakeAudit:
    def append(
        self,
        *,
        conversation_id: str,
        turn: int,
        node: Node,
        event: AuditEvent,
        payload: dict[str, JsonValue],
        versions: dict[str, JsonValue],
        case_id: str | None = None,
    ) -> AuditRecord:
        raise NotImplementedError

    def read(self, conversation_id: str) -> list[AuditRecord]:
        return []

    def verify_chain(self) -> bool:
        return True


class _FakeRunner:
    def start(self, customer_id: str | None) -> str:
        return "CV1"

    def send(self, conversation_id: str, text: str) -> TurnResult:
        return TurnResult(
            conversation_id=conversation_id, turn=1, reply_text="", outcome=Outcome.ANSWERED
        )


def test_fakes_conform_to_the_ports() -> None:
    search: KnowledgeSearch = _FakeSearch()
    audit: AuditLog = _FakeAudit()
    runner: DeskRunner = _FakeRunner()
    assert search.search("q", date(2024, 12, 1)) == []
    assert audit.verify_chain()
    assert runner.send(runner.start(None), "hi").outcome is Outcome.ANSWERED


# ---------- #31: AuditRecord accepted any string as its timestamp ----------
# Found by /code-review on PR #29 (both axes). The audit trail needs unambiguous UTC times.
def _record(at: Any) -> AuditRecord:
    return AuditRecord(
        audit_id=1,
        conversation_id="CV1",
        turn=1,
        at=at,
        node=Node.RESPOND,
        event=AuditEvent.ANSWERED,
        payload={},
        versions={},
        prev_hash="0",
        row_hash="1",
    )


@pytest.mark.parametrize("at", ["yesterday", datetime(2026, 11, 9, 12, 0)])
def test_issue_31_audit_time_must_be_timezone_aware(at: Any) -> None:
    with pytest.raises(ValidationError):
        _record(at)


def test_issue_31_aware_utc_time_is_accepted() -> None:
    assert _record(datetime(2026, 11, 9, 12, 0, tzinfo=UTC)).at.tzinfo is not None


# ---------- #32: AuditLog.append accepted values AuditRecord would refuse ----------
# Found by /code-review on PR #29 (standards axis). A non-JSON payload must fail at the caller's
# type check, not inside the data lane after the caller has acted.
@pytest.mark.parametrize("field", ["payload", "versions"])
def test_issue_32_append_types_match_the_record(field: str) -> None:
    append_hints = typing.get_type_hints(AuditLog.append)
    record_hints = typing.get_type_hints(AuditRecord)
    assert append_hints[field] == record_hints[field]
