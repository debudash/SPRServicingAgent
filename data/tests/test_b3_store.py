"""Issue #87: quote calculator, proposal and approval stores, idempotent ledger, policy source."""

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from contracts.messages import (
    Approval,
    Confirmation,
    Decision,
    Proposal,
    ProposalStatus,
    Quote,
    QuoteRefusal,
    QuoteRefusalReason,
    ThresholdTier,
    proposal_hash,
)
from contracts.money import to_cents
from contracts.ports import (
    ApprovalStore,
    AuditEvent,
    ExecutionRefused,
    ExecutionRefusedReason,
    Ledger,
    PolicySource,
    ProposalStore,
    QuoteService,
)
from contracts.tokens import approval_token
from contracts.tools import Node
from data.identity import SqliteIdentityCheck
from data.knowledge_index.index import ChromaKnowledgeSearch
from data.knowledge_index.loader import load_chunks
from data.knowledge_index.policy import POLICY_DOC_IDS, ChromaPolicySource
from data.settings import load_settings
from data.store.accounts import SqliteAccountStore
from data.store.audit import SqliteAuditLog
from data.store.db import open_db
from data.store.ledger import SqliteLedger
from data.store.proposals import SqliteApprovalStore, SqliteProposalStore
from data.store.quotes import SqliteQuoteService, surrender_rate_bp, threshold_tier
from data.store.seed import seed_starter_kit
from data.tests.test_knowledge_index import HashingEmbedding

AS_OF = date(2024, 12, 1)
REPO = Path(__file__).resolve().parents[2]
SECRET = b"test-approval-secret"
VERSIONS: dict[str, Any] = {"contracts": "0.5.0", "models": {}, "prompts": {}, "documents": {}}


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = open_db(tmp_path / "desk.db")
    seed_starter_kit(c)
    return c


def _quotes(conn: sqlite3.Connection) -> SqliteQuoteService:
    return SqliteQuoteService(SqliteAccountStore(conn, SqliteIdentityCheck(conn)))


def _quote(conn: sqlite3.Connection, customer_id: str, amount_cents: int) -> Quote:
    q = _quotes(conn).quote(customer_id, amount_cents, AS_OF)
    assert isinstance(q, Quote)
    return q


def _cents(text: str) -> int:
    return to_cents(Decimal(text))


def _withdrawal(conn: sqlite3.Connection, customer_id: str, year: int, gross: int) -> None:
    conn.execute(
        "INSERT INTO transactions (transaction_id, customer_id, proposal_id, contract_year, "
        "gross_cents, free_cents, excess_cents, charge_cents, net_cents, approved_by, "
        "executed_as_of, is_synthetic) VALUES (?, ?, NULL, ?, ?, ?, 0, 0, ?, 'seed', ?, 1)",
        (f"T-{customer_id}-{year}", customer_id, year, gross, gross, gross, AS_OF.isoformat()),
    )


def _synthetic_account(conn: sqlite3.Connection, cid: str, status: str, start: str) -> None:
    conn.execute(
        "INSERT INTO accounts (customer_id, name, account_status, gate_a_trusted, balance_cents, "
        "initial_deposit_cents, contract_start_date, is_synthetic) "
        "VALUES (?, 'Synthetic', ?, 1, 5000000, 5000000, ?, 1)",
        (cid, status, start),
    )
    SqliteIdentityCheck(conn).store(cid, "1950-01-01", "0000")


# ---------- the quote calculator (FR-05, FR-06, FR-07, D-02, D-05) ----------
def _golden_quote_cases() -> list[Any]:
    data = yaml.safe_load((REPO / "evals" / "golden" / "golden.yaml").read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    return [pytest.param(c, id=c["id"]) for c in cases if "quote" in c]


@pytest.mark.parametrize("case", _golden_quote_cases())
def test_every_golden_quote_is_reproduced_to_the_cent(
    conn: sqlite3.Connection, case: dict[str, Any]
) -> None:
    want = case["quote"]
    got = _quote(conn, case["customer"], _cents(want["amount"]))
    assert got.amount_cents == _cents(want["amount"])
    assert got.free_cents == _cents(want["free"])
    assert got.excess_cents == _cents(want["excess"])
    assert got.rate_bp == int(want["rate"].rstrip("%")) * 100
    assert got.charge_cents == _cents(want["charge"])
    assert got.net_cents == _cents(want["net"])
    assert got.threshold_tier is ThresholdTier(want["threshold_tier"])
    assert got.irs_notice is want["irs_notice"]


def test_there_is_at_least_one_golden_quote() -> None:
    assert len(_golden_quote_cases()) >= 4


@pytest.mark.parametrize(
    ("year", "bp"), [(1, 800), (2, 700), (3, 600), (4, 500), (5, 300), (6, 100), (7, 0), (12, 0)]
)
def test_surrender_rates_follow_the_fee_schedule(year: int, bp: int) -> None:
    assert surrender_rate_bp(year) == bp  # year 5 is 3%, not 4% (fee_schedule.md note)


@pytest.mark.parametrize(
    ("amount", "balance", "tier"),
    [
        (2_500_000, 10_000_000, ThresholdTier.SELF_SERVICE),  # exactly $25,000 is not over
        (2_500_001, 10_000_000, ThresholdTier.HUMAN),  # over $25,000
        (500_000, 1_000_000, ThresholdTier.SELF_SERVICE),  # exactly 50% is not over
        (500_001, 1_000_000, ThresholdTier.HUMAN),  # over 50% of the balance
    ],
)
def test_threshold_tier_is_d_02(amount: int, balance: int, tier: ThresholdTier) -> None:
    assert threshold_tier(amount, balance) is tier


def test_a_large_quote_is_human_tier(conn: sqlite3.Connection) -> None:
    assert _quote(conn, "SPR-1001", 3_000_000).threshold_tier is ThresholdTier.HUMAN


def test_this_years_withdrawals_reduce_the_free_amount(conn: sqlite3.Connection) -> None:
    _withdrawal(conn, "SPR-1001", 3, 500_000)
    q = _quote(conn, "SPR-1001", 2_000_000)
    assert q.free_cents == 874_506 - 500_000
    assert q.excess_cents == 2_000_000 - 374_506


@pytest.mark.parametrize(
    ("amount", "reason"),
    [
        (0, QuoteRefusalReason.NOT_POSITIVE),
        (-100, QuoteRefusalReason.NOT_POSITIVE),
        (10_000_000, QuoteRefusalReason.OVER_BALANCE),  # G-B3-05: more than $87,450.62
        (8_745_063, QuoteRefusalReason.OVER_BALANCE),  # one cent over
    ],
)
def test_fr_07_refusals(conn: sqlite3.Connection, amount: int, reason: QuoteRefusalReason) -> None:
    assert _quotes(conn).quote("SPR-1001", amount, AS_OF) == QuoteRefusal(reason=reason)


def test_the_whole_balance_can_be_quoted(conn: sqlite3.Connection) -> None:
    assert _quote(conn, "SPR-1001", 8_745_062).net_cents > 0  # a full surrender is quoted


@pytest.mark.parametrize("status", ["frozen", "deceased"])
def test_a_non_active_account_is_refused(conn: sqlite3.Connection, status: str) -> None:
    _synthetic_account(conn, "SYN-1", status, "2020-01-01")
    refusal = _quotes(conn).quote("SYN-1", 100_000, AS_OF)
    assert refusal == QuoteRefusal(reason=QuoteRefusalReason.NOT_ACTIVE)


def test_an_unknown_customer_raises_key_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        _quotes(conn).quote("SPR-9999", 100_000, AS_OF)


# ---------- proposals (GR-17, ARCHITECTURE 2.2) ----------
def _proposal(conn: sqlite3.Connection, pid: str = "P-1", amount: int = 2_000_000) -> Proposal:
    q = _quote(conn, "SPR-1001", amount)
    return Proposal(
        proposal_id=pid,
        conversation_id="CV1",
        customer_id="SPR-1001",
        quote=q,
        as_of=AS_OF,
        quoted_turn=1,
        hash=proposal_hash("SPR-1001", q, AS_OF),
    )


def test_a_saved_proposal_reads_back_quoted(conn: sqlite3.Connection) -> None:
    store = SqliteProposalStore(conn)
    p = _proposal(conn)
    store.save(p)
    assert store.get("P-1") == p
    assert store.status("P-1") is ProposalStatus.QUOTED
    assert store.get("P-2") is None
    with pytest.raises(KeyError):
        store.status("P-2")


def test_a_duplicate_proposal_id_raises(conn: sqlite3.Connection) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    with pytest.raises(sqlite3.IntegrityError):
        store.save(_proposal(conn))


def test_a_later_yes_for_the_quoted_amount_confirms(conn: sqlite3.Connection) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    store.confirm(Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2), "CV1")
    assert store.status("P-1") is ProposalStatus.CONFIRMED
    row = conn.execute("SELECT confirmed_turn FROM proposals WHERE proposal_id = 'P-1'")
    assert row.fetchone()[0] == 2


@pytest.mark.parametrize(
    ("confirmation", "conversation_id"),
    [
        (Confirmation(proposal_id="P-1", amount_cents=2_200_000, turn=2), "CV1"),  # BH-B3-02
        (Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=1), "CV1"),  # same turn
        (Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2), "CV2"),  # other session
    ],
)
def test_any_other_yes_is_refused_and_changes_nothing(
    conn: sqlite3.Connection, confirmation: Confirmation, conversation_id: str
) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    with pytest.raises(ValueError):
        store.confirm(confirmation, conversation_id)
    assert store.status("P-1") is ProposalStatus.QUOTED


def test_a_yes_for_an_unknown_proposal_raises_key_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        SqliteProposalStore(conn).confirm(
            Confirmation(proposal_id="P-9", amount_cents=1, turn=2), "CV1"
        )


def test_a_second_yes_is_refused(conn: sqlite3.Connection) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    yes = Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2)
    store.confirm(yes, "CV1")
    with pytest.raises(ValueError):  # confirmed -> confirmed is not a move
        store.confirm(yes.model_copy(update={"turn": 3}), "CV1")
    assert conn.execute("SELECT confirmed_turn FROM proposals").fetchone()[0] == 2


def test_illegal_moves_raise_and_change_nothing(conn: sqlite3.Connection) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    with pytest.raises(ValueError):
        store.move("P-1", ProposalStatus.EXECUTED)
    with pytest.raises(ValueError):
        store.move("P-1", ProposalStatus.APPROVED)  # no approval without a yes
    assert store.status("P-1") is ProposalStatus.QUOTED
    store.move("P-1", ProposalStatus.VOIDED)
    with pytest.raises(ValueError):
        store.move("P-1", ProposalStatus.CONFIRMED)  # voided is final


def test_the_database_refuses_an_unknown_status(conn: sqlite3.Connection) -> None:
    SqliteProposalStore(conn).save(_proposal(conn))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE proposals SET status = 'paid' WHERE proposal_id = 'P-1'")


# ---------- approvals (DECISION_MOVES) ----------
def _confirmed(conn: sqlite3.Connection, pid: str = "P-1", amount: int = 2_000_000) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn, pid, amount))
    store.confirm(Confirmation(proposal_id=pid, amount_cents=amount, turn=2), "CV1")


def _token(conn: sqlite3.Connection, pid: str = "P-1") -> str:
    proposal = SqliteProposalStore(conn).get(pid)
    assert proposal is not None
    return approval_token(pid, proposal.hash, SECRET)


def _approve(conn: sqlite3.Connection, pid: str = "P-1", approver: str = "compliance") -> str:
    token = _token(conn, pid)
    SqliteApprovalStore(conn).record(
        Approval(
            approval_id=f"A-{pid}-{approver}",
            proposal_id=pid,
            approver=approver,
            decision=Decision.APPROVE,
            token_hmac=token,
        )
    )
    return token


def _decide(conn: sqlite3.Connection, approver: str, decision: Decision, aid: str) -> None:
    SqliteApprovalStore(conn).record(
        Approval(approval_id=aid, proposal_id="P-1", approver=approver, decision=decision)
    )


def test_a_compliance_approval_moves_the_proposal_to_approved(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    token = _approve(conn)
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.APPROVED
    row = conn.execute("SELECT approver, decision, token_hmac, used_at_turn FROM approvals")
    assert row.fetchone() == ("compliance", "approve", token, None)


@pytest.mark.parametrize("decision", [Decision.HOLD, Decision.ESCALATE])
def test_hold_and_escalate_go_to_a_human(conn: sqlite3.Connection, decision: Decision) -> None:
    _confirmed(conn)
    _decide(conn, "compliance", decision, "A-1")
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.ESCALATED


def test_human_decisions_on_an_escalated_proposal(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    _decide(conn, "compliance", Decision.HOLD, "A-1")
    _decide(conn, "human:r1", Decision.REQUEST_INFO, "A-2")
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.ESCALATED
    _decide(conn, "human:r1", Decision.REJECT, "A-3")
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.VOIDED


def test_a_human_can_approve_an_escalated_proposal(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    _decide(conn, "compliance", Decision.ESCALATE, "A-1")
    _approve(conn, approver="human:r1")
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.APPROVED


def test_compliance_cannot_decide_an_escalated_proposal(conn: sqlite3.Connection) -> None:
    # An escalated proposal belongs to a human (B4); Compliance approving it would bypass review.
    _confirmed(conn)
    _decide(conn, "compliance", Decision.HOLD, "A-1")
    with pytest.raises(ValueError):
        _approve(conn)
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.ESCALATED
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


def test_a_reviewer_cannot_stand_in_for_compliance(conn: sqlite3.Connection) -> None:
    # A human decides only what was sent to a human; a confirmed proposal goes to Compliance first.
    _confirmed(conn)
    with pytest.raises(ValueError):
        _approve(conn, approver="human:r1")
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.CONFIRMED
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_compliance_cannot_approve_a_human_tier_proposal(conn: sqlite3.Connection) -> None:
    # FR-08 / D-02: only the self-service tier executes on Compliance's approval.
    _confirmed(conn, amount=3_000_000)
    with pytest.raises(ValueError):
        _approve(conn)
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.CONFIRMED
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_an_approval_before_the_yes_is_refused_and_not_stored(conn: sqlite3.Connection) -> None:
    SqliteProposalStore(conn).save(_proposal(conn))
    with pytest.raises(ValueError):  # quoted -> approved is not a move (GR-17)
        _approve(conn)
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_an_approval_for_an_unknown_proposal_raises_key_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        _decide(conn, "compliance", Decision.HOLD, "A-1")


# ---------- the ledger (FR-08 to FR-10, FR-26) ----------
def _ledger(conn: sqlite3.Connection, enabled: bool = True) -> SqliteLedger:
    return SqliteLedger(conn, SqliteAuditLog(conn), secret=SECRET, execution_enabled=enabled)


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def _transactions(conn: sqlite3.Connection) -> int:
    return _count(conn, "SELECT COUNT(*) FROM transactions WHERE proposal_id IS NOT NULL")


def _executed_rows(conn: sqlite3.Connection) -> int:
    return _count(conn, "SELECT COUNT(*) FROM audit WHERE event = 'executed'")


def _refused(ledger: SqliteLedger, pid: str, token: str) -> ExecutionRefusedReason:
    with pytest.raises(ExecutionRefused) as err:
        ledger.execute(pid, token, 3, VERSIONS)
    return err.value.reason


def test_an_approved_proposal_executes_once_with_its_audit_row(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    token = _approve(conn)
    execution = _ledger(conn).execute("P-1", token, 3, VERSIONS)
    assert execution.proposal_id == "P-1"
    assert execution.approved_by == "compliance"
    tx = conn.execute(
        "SELECT transaction_id, customer_id, contract_year, gross_cents, free_cents, "
        "excess_cents, charge_cents, net_cents, approved_by, executed_as_of FROM transactions "
        "WHERE proposal_id = 'P-1'"
    ).fetchone()
    assert tx == (
        execution.transaction_id,
        "SPR-1001",
        3,
        2_000_000,
        874_506,
        1_125_494,
        67_530,
        1_932_470,
        "compliance",
        "2024-12-01",
    )
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.EXECUTED
    assert _count(conn, "SELECT used_at_turn FROM approvals") == 3
    [row] = [r for r in SqliteAuditLog(conn).read("CV1") if r.event is AuditEvent.EXECUTED]
    assert row.node is Node.EXECUTE
    assert row.turn == 3
    assert row.payload == {
        "proposal_id": "P-1",
        "transaction_id": execution.transaction_id,
        "approved_by": "compliance",
    }
    assert row.versions == VERSIONS
    assert SqliteAuditLog(conn).verify_chain()


def test_only_the_used_part_of_the_allowance_is_recorded_as_free(conn: sqlite3.Connection) -> None:
    _confirmed(conn, amount=500_000)  # under the $8,745.06 allowance
    _ledger(conn).execute("P-1", _approve(conn), 3, VERSIONS)
    row = conn.execute("SELECT free_cents, excess_cents FROM transactions WHERE proposal_id='P-1'")
    assert row.fetchone() == (500_000, 0)
    assert _quote(conn, "SPR-1001", 100_000).free_cents == 874_506 - 500_000  # D-05 counts it


def test_a_replay_returns_the_first_execution_and_writes_nothing(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    token = _approve(conn)
    first = _ledger(conn).execute("P-1", token, 3, VERSIONS)
    again = _ledger(conn).execute("P-1", token, 4, VERSIONS)  # FR-09
    assert again == first
    assert _transactions(conn) == 1
    assert _executed_rows(conn) == 1
    assert _count(conn, "SELECT used_at_turn FROM approvals") == 3


def test_a_replay_with_another_token_is_refused(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    _ledger(conn).execute("P-1", _approve(conn), 3, VERSIONS)
    assert _refused(_ledger(conn), "P-1", "0" * 64) is ExecutionRefusedReason.TOKEN_INVALID
    assert _transactions(conn) == 1


def test_an_unknown_proposal_is_refused(conn: sqlite3.Connection) -> None:
    assert _refused(_ledger(conn), "P-9", "t") is ExecutionRefusedReason.UNKNOWN_PROPOSAL


@pytest.mark.parametrize("stage", ["quoted", "confirmed", "escalated", "voided"])
def test_only_an_approved_proposal_executes(conn: sqlite3.Connection, stage: str) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    if stage != "quoted":
        store.confirm(Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2), "CV1")
    if stage in {"escalated", "voided"}:
        store.move("P-1", ProposalStatus(stage))
    reason = _refused(_ledger(conn), "P-1", _token(conn))
    assert reason is ExecutionRefusedReason.NOT_APPROVED
    assert _transactions(conn) == 0


def test_a_wrong_token_is_refused(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    _approve(conn)
    wrong = approval_token("P-1", _token(conn), b"another-secret")
    assert _refused(_ledger(conn), "P-1", wrong) is ExecutionRefusedReason.TOKEN_INVALID
    assert _transactions(conn) == 0
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.APPROVED


def test_another_proposals_token_is_refused(conn: sqlite3.Connection) -> None:
    # The same figures, customer and day: only the proposal ID tells the tokens apart (#93).
    _confirmed(conn, "P-1")
    _confirmed(conn, "P-2")
    _approve(conn, "P-1")
    token_2 = _approve(conn, "P-2")
    assert _refused(_ledger(conn), "P-1", token_2) is ExecutionRefusedReason.TOKEN_INVALID
    assert _transactions(conn) == 0


def test_a_superseded_approval_token_is_refused(conn: sqlite3.Connection) -> None:
    # Approved, sent to a human (FR-26 after approval, #94), approved again: the first token is
    # dead. Here both tokens are equal (same ID and hash), so the stored row decides.
    _confirmed(conn)
    _approve(conn)
    SqliteProposalStore(conn).move("P-1", ProposalStatus.ESCALATED)
    token = _approve(conn, approver="human:r1")
    execution = _ledger(conn).execute("P-1", token, 3, VERSIONS)
    assert execution.approved_by == "human:r1"
    used = conn.execute("SELECT approver FROM approvals WHERE used_at_turn IS NOT NULL")
    assert [r[0] for r in used.fetchall()] == ["human:r1"]


def test_a_tampered_stored_token_is_refused(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    _approve(conn)
    conn.execute("UPDATE approvals SET token_hmac = 'forged'")
    assert _refused(_ledger(conn), "P-1", "forged") is ExecutionRefusedReason.TOKEN_INVALID
    assert _transactions(conn) == 0


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE proposals SET amount_cents = 3000000, net_cents = 2932470",
        "UPDATE proposals SET charge_cents = 0, net_cents = 2000000",
        "UPDATE proposals SET as_of = '2024-12-02'",
        "UPDATE proposals SET customer_id = 'SPR-1004'",
    ],
)
def test_a_changed_proposal_is_refused(conn: sqlite3.Connection, tamper: str) -> None:
    _confirmed(conn)
    token = _approve(conn)
    conn.execute(tamper)
    reason = _refused(_ledger(conn), "P-1", token)
    assert reason is ExecutionRefusedReason.HASH_CHANGED
    assert _transactions(conn) == 0
    assert _executed_rows(conn) == 0


def test_the_kill_switch_refuses_any_approver(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    _decide(conn, "compliance", Decision.ESCALATE, "A-1")
    token = _approve(conn, approver="human:r1")
    off = _ledger(conn, enabled=False)
    assert _refused(off, "P-1", token) is ExecutionRefusedReason.EXECUTION_DISABLED
    assert _transactions(conn) == 0
    assert _count(conn, "SELECT COUNT(*) FROM approvals WHERE used_at_turn IS NOT NULL") == 0


def test_a_replay_still_answers_with_the_kill_switch_on(conn: sqlite3.Connection) -> None:
    # Check 2 comes before check 3: the money already moved, so the replay reports it.
    _confirmed(conn)
    token = _approve(conn)
    first = _ledger(conn).execute("P-1", token, 3, VERSIONS)
    assert _ledger(conn, enabled=False).execute("P-1", token, 4, VERSIONS) == first


def test_no_partial_writes_when_the_audit_row_fails(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _confirmed(conn)
    token = _approve(conn)

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(SqliteAuditLog, "append_in_transaction", broken)
    with pytest.raises(RuntimeError):
        _ledger(conn).execute("P-1", token, 3, VERSIONS)
    assert _transactions(conn) == 0
    assert SqliteProposalStore(conn).status("P-1") is ProposalStatus.APPROVED
    assert _count(conn, "SELECT COUNT(*) FROM approvals WHERE used_at_turn IS NOT NULL") == 0
    assert not conn.in_transaction
    monkeypatch.undo()
    assert _ledger(conn).execute("P-1", token, 3, VERSIONS).proposal_id == "P-1"


def test_an_empty_secret_executes_nothing(conn: sqlite3.Connection) -> None:
    _confirmed(conn)
    token = _approve(conn)
    ledger = SqliteLedger(conn, SqliteAuditLog(conn), secret=b"", execution_enabled=True)
    with pytest.raises(ValueError):
        ledger.execute("P-1", token, 3, VERSIONS)
    assert _transactions(conn) == 0
    assert not conn.in_transaction


# ---------- settings (FR-26, GR-18) ----------
def test_execution_is_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
    assert load_settings().execution_enabled


@pytest.mark.parametrize(
    ("raw", "enabled"),
    [("true", True), ("TRUE", True), ("false", False), ("0", False), ("flase", False)],
)
def test_anything_but_true_switches_execution_off(
    monkeypatch: pytest.MonkeyPatch, raw: str, enabled: bool
) -> None:
    monkeypatch.setenv("EXECUTION_ENABLED", raw)  # a typo fails closed
    assert load_settings().execution_enabled is enabled


def test_the_approval_secret_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPROVAL_SECRET", "abc")
    assert load_settings().approval_secret == b"abc"
    monkeypatch.delenv("APPROVAL_SECRET")
    assert load_settings().approval_secret == b""


# ---------- the policy source (FR-22: Compliance reads policy documents only) ----------
def test_policy_source_returns_only_policy_documents(tmp_path: Path) -> None:
    index = ChromaKnowledgeSearch(tmp_path / "chroma", HashingEmbedding())
    index.rebuild(load_chunks(REPO / "knowledge"))
    policy = ChromaPolicySource(index)
    # A product question that the fee schedule answers best still gets only policy chunks.
    chunks = policy.get_policy("surrender charge rate in year 5", AS_OF, k=4)
    assert chunks
    assert {c.doc_id for c in chunks} <= POLICY_DOC_IDS
    large = policy.get_policy("withdrawal over $25,000 large withdrawal", AS_OF, k=2)
    assert "large_withdrawal_policy" in {c.doc_id for c in large}


def test_policy_documents_exist_in_the_knowledge_folder() -> None:
    names = {p.stem for p in (REPO / "knowledge").glob("*.md")}
    assert POLICY_DOC_IDS <= names


def test_no_policy_is_in_force_before_its_effective_date(tmp_path: Path) -> None:
    index = ChromaKnowledgeSearch(tmp_path / "chroma", HashingEmbedding())
    index.rebuild(load_chunks(REPO / "knowledge"))
    assert ChromaPolicySource(index).get_policy("large withdrawal", date(2023, 6, 1)) == []


# ---------- the adapters conform to the ports ----------
def test_adapters_conform_to_the_b3_ports(conn: sqlite3.Connection, tmp_path: Path) -> None:
    quotes: QuoteService = _quotes(conn)
    proposals: ProposalStore = SqliteProposalStore(conn)
    approvals: ApprovalStore = SqliteApprovalStore(conn)
    ledger: Ledger = _ledger(conn)
    policy: PolicySource = ChromaPolicySource(
        ChromaKnowledgeSearch(tmp_path / "chroma", HashingEmbedding())
    )
    assert all([quotes, proposals, approvals, ledger, policy])


# ---------- #99: move could set approved, confirmed or executed around their real paths ----------
# Found by /code-review on PR #96 (spec): move(EXECUTED) left an "executed" proposal, no money.
@pytest.mark.parametrize(
    ("setup", "target"),
    [
        ("quoted", ProposalStatus.CONFIRMED),
        ("confirmed", ProposalStatus.APPROVED),
        ("approved", ProposalStatus.EXECUTED),
    ],
)
def test_issue_99_move_cannot_stand_in_for_confirm_approve_or_execute(
    conn: sqlite3.Connection, setup: str, target: ProposalStatus
) -> None:
    store = SqliteProposalStore(conn)
    if setup == "quoted":
        store.save(_proposal(conn))
    else:
        _confirmed(conn)
    if setup == "approved":
        _approve(conn)
    before = store.status("P-1")
    with pytest.raises(ValueError):
        store.move("P-1", target)
    assert store.status("P-1") is before


# ---------- #98: a human approval executed a proposal the customer never confirmed ----------
# Found by /code-review on PR #96 (spec): quoted -> escalated -> human approve -> executed (FR-08).
def test_issue_98_no_approval_without_the_customers_yes(conn: sqlite3.Connection) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    store.move("P-1", ProposalStatus.ESCALATED)  # e.g. a human-tier quote sent to a case (#94)
    with pytest.raises(ValueError):
        _approve(conn, approver="human:r1")
    assert store.status("P-1") is ProposalStatus.ESCALATED
    assert _count(conn, "SELECT COUNT(*) FROM approvals") == 0
    reason = _refused(_ledger(conn), "P-1", _token(conn))
    assert reason is ExecutionRefusedReason.NOT_APPROVED
    assert _transactions(conn) == 0


def test_issue_98_a_reviewer_may_still_reject_an_unconfirmed_proposal(
    conn: sqlite3.Connection,
) -> None:
    store = SqliteProposalStore(conn)
    store.save(_proposal(conn))
    store.move("P-1", ProposalStatus.ESCALATED)
    _decide(conn, "human:r1", Decision.REJECT, "A-1")
    assert store.status("P-1") is ProposalStatus.VOIDED
