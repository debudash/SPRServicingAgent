"""Contract tests for the B1 ports (issue #28)."""

import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

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


def test_runner_has_no_way_to_skip_the_identity_challenge() -> None:
    # Issue #28 design: no start parameter may pre-pass Gate B.
    params = DeskRunner.start.__code__.co_varnames[: DeskRunner.start.__code__.co_argcount]
    assert params == ("self", "customer_id")


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
        payload: dict[str, Any],
        versions: dict[str, Any],
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
