"""B1 graph and runner: G-B1-01..07 paths with scripted models, a fake search, an in-memory log."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from agents.graph import apply_writes
from agents.nodes import concierge as concierge_node
from agents.nodes.common import Stores, TurnContext
from agents.nodes.knowledge import KnowledgeDraft
from agents.runner import GraphDeskRunner
from agents.testing import (
    MemoryAccounts,
    MemoryCases,
    MemoryIdentity,
    MemoryPasswords,
    MemoryProposals,
    MemoryQuotes,
    ScriptedChatModel,
)
from contracts.messages import Citation, Intent, IntentKind, KnowledgeAnswer
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, AuditRecord, KnowledgeChunk
from contracts.state import (
    MAX_HOPS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    ContractViolation,
    ConversationState,
    Versions,
)
from contracts.tools import Node, Role, Step

AS_OF = date(2026, 3, 1)


def chunk(doc: str, section: str, text: str, version: int = 1) -> KnowledgeChunk:
    return KnowledgeChunk(
        doc_id=doc,
        version=version,
        effective_date=date(2025, 1, 1),
        section=section,
        text=text,
        source_path=f"knowledge/{doc}.md",
    )


FEES = chunk("fee_schedule", "Year 5", "Year 5 surrender charge is 3%.")


class FakeSearch:
    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self.chunks = chunks
        self.queries: list[tuple[str, date]] = []

    def search(self, query: str, as_of: date, k: int = 4) -> list[KnowledgeChunk]:
        self.queries.append((query, as_of))
        return self.chunks


class MemoryAudit:
    def __init__(self) -> None:
        self.rows: list[AuditRecord] = []

    def append(self, **kw: Any) -> AuditRecord:
        row = AuditRecord(
            audit_id=len(self.rows) + 1,
            at=datetime.now(UTC),
            prev_hash="p",
            row_hash="h",
            **kw,
        )
        self.rows.append(row)
        return row

    def read(self, conversation_id: str) -> list[AuditRecord]:
        return [r for r in self.rows if r.conversation_id == conversation_id]

    def verify_chain(self) -> bool:
        return True


def no_accounts() -> Stores:
    """B2 stores with no accounts in them, for runs that never reach an account."""
    return Stores(
        accounts=MemoryAccounts({}, trusted=set()),
        identity=MemoryIdentity({}),
        cases=MemoryCases(),
        passwords=MemoryPasswords({}),
        quotes=MemoryQuotes(),
        proposals=MemoryProposals(),
    )


def make_runner(
    intent: IntentKind | None,
    drafts: list[Any],
    chunks: list[KnowledgeChunk],
) -> tuple[GraphDeskRunner, FakeSearch, MemoryAudit]:
    search, audit = FakeSearch(chunks), MemoryAudit()
    concierge = ScriptedChatModel([Intent(kind=intent)] if intent else [])
    knowledge = ScriptedChatModel(drafts)
    runner = GraphDeskRunner(
        search,
        audit,
        models={Role.CONCIERGE: concierge, Role.KNOWLEDGE: knowledge},
        clock=lambda: AS_OF,
        stores=no_accounts(),
    )
    return runner, search, audit


def ask(runner: GraphDeskRunner, text: str = "question") -> Any:
    return runner.send(runner.start(None), text)


def cited(chunk_: KnowledgeChunk, text: str) -> KnowledgeDraft:
    return KnowledgeDraft(
        found=True,
        text=text,
        citations=(Citation(doc_id=chunk_.doc_id, version=chunk_.version, section=chunk_.section),),
    )


def test_product_question_is_answered_with_citation() -> None:  # G-B1-01/02/03/07
    runner, search, audit = make_runner(
        IntentKind.PRODUCT_QUESTION, [cited(FEES, "Year 5 is 3%.")], [FEES]
    )
    r = ask(runner, "Is the year 5 charge 4%?")
    assert r.outcome is Outcome.ANSWERED
    assert "3%" in r.reply_text
    assert r.citations == (Citation(doc_id="fee_schedule", version=1, section="Year 5"),)
    assert r.steps == (Step.SEARCH_KB,)
    assert r.nodes == (Node.INTAKE, Node.CONCIERGE, Node.KNOWLEDGE, Node.RESPOND)
    assert search.queries == [("Is the year 5 charge 4%?", AS_OF)]
    assert [row.event for row in audit.rows] == [AuditEvent.ANSWERED]
    assert audit.rows[0].versions["documents"] == {"fee_schedule": 1}
    assert audit.rows[0].versions["prompts"] == {
        "concierge": "5",
        "knowledge": "1",
        "compliance": "1",
    }


def test_unsupported_question_is_no_source() -> None:  # G-B1-04
    runner, _, audit = make_runner(
        IntentKind.PRODUCT_QUESTION, [KnowledgeDraft(found=False, text="x")], [FEES]
    )
    r = ask(runner)
    assert r.outcome is Outcome.NO_SOURCE
    assert r.citations == ()
    assert audit.rows[0].event is AuditEvent.REFUSED


def test_empty_search_is_no_source_without_a_model_call() -> None:
    runner, _, _ = make_runner(IntentKind.PRODUCT_QUESTION, [], [])
    assert ask(runner).outcome is Outcome.NO_SOURCE


def test_citation_not_retrieved_fails_closed_to_no_source() -> None:
    bogus = KnowledgeDraft(
        found=True, text="Made up.", citations=(Citation(doc_id="faq", version=9, section="Z"),)
    )
    runner, _, _ = make_runner(IntentKind.PRODUCT_QUESTION, [bogus], [FEES])
    r = ask(runner)
    assert r.outcome is Outcome.NO_SOURCE
    assert r.citations == ()


@pytest.mark.parametrize("kind", [IntentKind.OUT_OF_SCOPE])
def test_out_of_scope_skips_knowledge(kind: IntentKind) -> None:  # G-B1-05/06
    runner, search, audit = make_runner(kind, [], [FEES])
    r = ask(runner)
    assert r.outcome is Outcome.OUT_OF_SCOPE
    assert r.steps == ()
    assert r.nodes == (Node.INTAKE, Node.CONCIERGE, Node.RESPOND)
    assert search.queries == []
    assert len(audit.rows) == 1


def test_change_details_is_not_permitted_yet() -> None:
    # account_info left the not-yet list in B2 (#59), withdrawal in B3 (#88), and full surrender
    # and hardship waivers in B4 (#146): see test_review_desk.py.
    runner, search, audit = make_runner(IntentKind.CHANGE_DETAILS, [], [FEES])
    r = ask(runner)
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "yet" in r.reply_text
    assert search.queries == []
    assert [row.event for row in audit.rows] == [AuditEvent.REFUSED]


def test_a_guest_asking_for_a_full_surrender_is_asked_to_log_in() -> None:
    # B4 (#146): a person handles it (NG-07), but a case names its customer, so a guest gets no
    # case and nothing is looked up.
    runner, search, audit = make_runner(IntentKind.FULL_SURRENDER, [], [FEES])
    r = ask(runner, "Close it out, I want everything.")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "log in" in r.reply_text
    assert search.queries == [] and Step.CREATE_CASE not in r.steps
    assert [row.event for row in audit.rows] == [AuditEvent.REFUSED]


def test_a_guest_asking_about_a_waiver_gets_the_documents_and_no_case() -> None:
    # B4 (#146): FR-13's documentation answer from the knowledge base; no account, so no case.
    draft = cited(FEES, "Waivers need documentation; see the FAQ.")
    runner, search, _ = make_runner(IntentKind.HARDSHIP_WAIVER, [draft], [FEES])
    r = ask(runner, "I'm terminally ill. Do I have to pay the surrender fee?")
    assert r.outcome is Outcome.ANSWERED
    assert search.queries and Step.CREATE_CASE not in r.steps
    assert r.citations


def test_tool_loop_hits_budget_and_is_unavailable() -> None:
    again = KnowledgeDraft(search_query="more")
    runner, search, audit = make_runner(IntentKind.PRODUCT_QUESTION, [again] * 20, [FEES])
    r = ask(runner)
    assert r.outcome is Outcome.UNAVAILABLE
    assert len(search.queries) == MAX_TOOL_CALLS_PER_TURN
    assert r.steps == (Step.SEARCH_KB,) * MAX_TOOL_CALLS_PER_TURN
    assert len(audit.rows) == 1


def test_model_error_is_unavailable_and_flagged() -> None:
    runner, _, audit = make_runner(IntentKind.PRODUCT_QUESTION, [], [FEES])  # no queued draft
    r = ask(runner)
    assert r.outcome is Outcome.UNAVAILABLE
    assert r.provider_error
    assert len(audit.rows) == 1


def test_every_turn_writes_exactly_one_audit_row() -> None:
    runner, _, audit = make_runner(IntentKind.OUT_OF_SCOPE, [], [])
    cid = runner.start(None)
    runner._models[Role.CONCIERGE].queue(Intent(kind=IntentKind.OUT_OF_SCOPE))  # type: ignore[attr-defined]
    runner.send(cid, "one")
    runner.send(cid, "two")
    assert [r.turn for r in audit.read(cid)] == [1, 2]


def test_hop_budget_ends_turn_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agents.graph.MAX_HOPS_PER_TURN", 1)
    runner, _, audit = make_runner(IntentKind.OUT_OF_SCOPE, [], [])
    r = ask(runner)
    assert MAX_HOPS_PER_TURN == 8
    assert r.outcome is Outcome.UNAVAILABLE
    assert len(audit.rows) == 1


def test_node_writing_unowned_field_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def make(deps: Any) -> Any:
        return lambda state: {"reply": None}  # the Concierge may not write `reply`

    monkeypatch.setattr(concierge_node, "make", make)
    runner, _, audit = make_runner(IntentKind.OUT_OF_SCOPE, [], [])
    r = ask(runner)
    assert r.outcome is Outcome.UNAVAILABLE
    assert [row.node for row in audit.rows] == [Node.RUNNER]


def test_apply_writes_enforces_ownership() -> None:
    state = ConversationState(
        conversation_id="c", as_of=AS_OF, versions=Versions(contracts="0.2.0")
    )
    with pytest.raises(ContractViolation):
        apply_writes(
            Node.CONCIERGE, state, {"knowledge_answer": KnowledgeAnswer(found=False, text="")}
        )
    with pytest.raises(ContractViolation):
        apply_writes(Node.INTAKE, state, {"session.gate_b_passed": True})
    assert (
        apply_writes(Node.INTAKE, state, {"session.customer_id": "SPR-1"})["session"].customer_id
        == "SPR-1"
    )


def test_turn_context_usage_starts_empty() -> None:
    assert TurnContext().usage().input_tokens == 0
