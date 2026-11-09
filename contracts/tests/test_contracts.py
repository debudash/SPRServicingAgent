"""Contract tests: the contracts agree with the golden set, the blueprint and the data model."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from contracts.classification import COLUMNS, RESTRICTED_FIELDS, Classification
from contracts.messages import (
    AccountView,
    Approval,
    ComplianceDecision,
    Decision,
    Execution,
    HumanDecision,
    Intent,
    IntentKind,
    KnowledgeAnswer,
    Proposal,
    Quote,
    Reason,
    Signal,
    ThresholdTier,
    proposal_hash,
)
from contracts.money import format_dollars, to_cents
from contracts.outcomes import FAILURE_OUTCOMES, Outcome
from contracts.state import (
    FIELD_WRITERS,
    SESSION_FIELD_WRITERS,
    ContractViolation,
    ConversationState,
    Session,
    check_write,
)
from contracts.tools import TOOL_SCOPE, Node, Role, Step, ToolName

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden"
AS_OF = date(2024, 12, 1)


def _golden_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for name in ("golden.yaml", "behavioural.yaml"):
        cases += yaml.safe_load((GOLDEN / name).read_text(encoding="utf-8"))["cases"]
    return cases


def _quote(amount: int = 2_000_000) -> Quote:
    # G-B3-01: SPR-1001, $20,000 in contract year 3.
    return Quote(
        amount_cents=amount,
        free_cents=874_506,
        excess_cents=amount - 874_506,
        rate_bp=600,
        charge_cents=round((amount - 874_506) * 0.06),
        net_cents=amount - round((amount - 874_506) * 0.06),
        contract_year=3,
        threshold_tier=ThresholdTier.SELF_SERVICE,
        irs_notice=False,
    )


# ---------- the golden set speaks the contracts' language ----------
def test_every_golden_outcome_is_a_contract_outcome() -> None:
    used = {c["expect"].get("outcome") or c["expect"].get("final_outcome") for c in _golden_cases()}
    assert used - {None} <= {o.value for o in Outcome}


def test_prd_failure_codes_are_exactly_the_failure_outcomes() -> None:
    assert {o.value for o in FAILURE_OUTCOMES} == {
        "NO_SOURCE",
        "NOT_PERMITTED",
        "NEEDS_HUMAN",
        "UNAVAILABLE",
        "OUT_OF_SCOPE",
    }


def test_every_golden_step_name_is_a_contract_step() -> None:
    used: set[str] = set()
    for c in _golden_cases():
        for key in ("tools", "not_tools", "order"):
            used |= set(c["expect"].get(key, []))
    assert used <= {s.value for s in Step}


# ---------- tool scope (FR-22, blueprint section 3, ADR 0005) ----------
def test_no_role_can_call_execute_and_the_concierge_has_no_tools() -> None:
    assert "execute" not in {t.value for t in ToolName}
    assert TOOL_SCOPE[Role.CONCIERGE] == frozenset()


def test_every_tool_belongs_to_exactly_one_role() -> None:
    owners = [t for tools in TOOL_SCOPE.values() for t in tools]
    assert sorted(owners) == sorted(ToolName)


# ---------- state ownership (FR-19, blueprint section 4) ----------
def test_every_state_field_has_exactly_one_writer() -> None:
    assert set(FIELD_WRITERS) == set(ConversationState.model_fields)
    assert set(SESSION_FIELD_WRITERS) == set(Session.model_fields)


def test_a_node_cannot_write_a_field_it_does_not_own() -> None:
    check_write(Node.COMPLIANCE, "compliance")
    check_write(Node.IDENTITY_GATE, "session.gate_b_passed")
    with pytest.raises(ContractViolation):
        check_write(Node.CONCIERGE, "approval")
    with pytest.raises(ContractViolation):
        check_write(Node.INTAKE, "session.gate_b_passed")
    with pytest.raises(ContractViolation):
        check_write(Node.EXECUTE, "no_such_field")


# ---------- classification (PG-04, GR-09) ----------
def test_restricted_fields_live_only_in_the_identity_table() -> None:
    assert RESTRICTED_FIELDS == {"dob", "ssn_last4"}
    for table, columns in COLUMNS.items():
        if table != "identity":
            assert Classification.RESTRICTED not in columns.values(), table


def test_no_message_a_model_sees_has_a_restricted_field() -> None:
    assert not RESTRICTED_FIELDS & set(AccountView.model_fields)
    assert not RESTRICTED_FIELDS & set(Session.model_fields)


# ---------- messages refuse what they should (FR-19) ----------
def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        Intent.model_validate({"kind": "withdrawal", "approved": True})


def test_a_found_answer_must_cite() -> None:
    with pytest.raises(ValidationError):
        KnowledgeAnswer(found=True, text="3% in year 5")
    KnowledgeAnswer(found=False, text="not covered")


def test_quote_figures_must_add_up() -> None:
    with pytest.raises(ValidationError):
        Quote(
            amount_cents=2_000_000,
            free_cents=874_506,
            excess_cents=1_125_494,
            rate_bp=600,
            charge_cents=67_530,
            net_cents=2_000_000,
            contract_year=3,
            threshold_tier=ThresholdTier.SELF_SERVICE,
            irs_notice=False,
        )


def test_compliance_cannot_reject_or_approve_a_signal() -> None:
    reason = (Reason(policy_ref="vulnerable_customer_policy v1 §Signals", text="caller pressure"),)
    with pytest.raises(ValidationError):
        ComplianceDecision(proposal_id="P1", decision=Decision.REJECT, reasons=reason)
    with pytest.raises(ValidationError):
        ComplianceDecision(
            proposal_id="P1",
            decision=Decision.APPROVE,
            reasons=reason,
            signals=frozenset({Signal.PRESSURE}),
        )
    with pytest.raises(ValidationError):
        ComplianceDecision(proposal_id="P1", decision=Decision.APPROVE, reasons=())


def test_reviewers_cannot_escalate() -> None:
    with pytest.raises(ValidationError):
        HumanDecision(case_id="C1", reviewer_id="r1", decision=Decision.ESCALATE)


# ---------- proposal hash (GR-18) ----------
def test_proposal_hash_is_deterministic_and_changes_with_the_amount() -> None:
    q = _quote()
    assert proposal_hash("SPR-1001", q, AS_OF) == proposal_hash("SPR-1001", q, AS_OF)
    assert proposal_hash("SPR-1001", q, AS_OF) != proposal_hash(
        "SPR-1001", _quote(2_200_000), AS_OF
    )
    assert proposal_hash("SPR-1001", q, AS_OF) != proposal_hash("SPR-1003", q, AS_OF)


def test_a_proposal_with_a_stale_hash_is_refused() -> None:
    q = _quote()
    good = proposal_hash("SPR-1001", q, AS_OF)
    Proposal(
        proposal_id="P1",
        conversation_id="CV1",
        customer_id="SPR-1001",
        quote=q,
        as_of=AS_OF,
        quoted_turn=1,
        hash=good,
    )
    with pytest.raises(ValidationError):
        Proposal(
            proposal_id="P1",
            conversation_id="CV1",
            customer_id="SPR-1001",
            quote=_quote(2_200_000),
            as_of=AS_OF,
            quoted_turn=1,
            hash=good,
        )


# ---------- money (GR-03) ----------
@pytest.mark.parametrize(
    ("dollars", "cents"),
    [("675.2964", 67_530), ("8745.062", 874_506), ("0.005", 1), ("0.004", 0), ("795.2964", 79_530)],
)
def test_rounding_is_half_up_to_the_cent(dollars: str, cents: int) -> None:
    assert to_cents(Decimal(dollars)) == cents


def test_customer_facing_format() -> None:
    assert format_dollars(1_932_470) == "$19,324.70"


def test_intent_kinds_cover_the_routes_in_the_blueprint() -> None:
    assert {"product_question", "withdrawal", "hardship_waiver", "third_party", "out_of_scope"} <= {
        k.value for k in IntentKind
    }


# ---------- #21: Approval accepted a token on a non-approve decision ----------
# Found by /code-review on PR #20 (both axes). A token is the authority to move money (GR-18).
@pytest.mark.parametrize(
    ("approver", "decision", "token"),
    [
        ("compliance", Decision.HOLD, "hmac"),  # token on a hold
        ("compliance", Decision.ESCALATE, "hmac"),  # token on an escalation
        ("compliance", Decision.APPROVE, None),  # approval to execute without a token
        ("compliance", Decision.REJECT, None),  # reviewer-only decision from Compliance
        ("human:r1", Decision.HOLD, None),  # Compliance-only decision from a reviewer
        ("someone", Decision.APPROVE, "hmac"),  # unknown approver
        ("human:", Decision.APPROVE, "hmac"),  # reviewer with no ID
    ],
)
def test_issue_21_approval_refuses_invalid_combinations(
    approver: str, decision: Decision, token: str | None
) -> None:
    with pytest.raises(ValidationError):
        Approval(
            approval_id="A1",
            proposal_id="P1",
            approver=approver,
            decision=decision,
            token_hmac=token,
        )


def test_issue_21_valid_approvals_pass() -> None:
    Approval(
        approval_id="A1",
        proposal_id="P1",
        approver="compliance",
        decision=Decision.APPROVE,
        token_hmac="hmac",
    )
    Approval(approval_id="A2", proposal_id="P1", approver="compliance", decision=Decision.HOLD)
    Approval(approval_id="A3", proposal_id="P1", approver="human:r1", decision=Decision.REJECT)


def test_issue_21_execution_names_a_valid_approver() -> None:
    with pytest.raises(ValidationError):
        Execution(transaction_id="T1", proposal_id="P1", approved_by="anyone")
    Execution(transaction_id="T1", proposal_id="P1", approved_by="human:r1")


# ---------- #22: Quote validated a wrong surrender charge ----------
# Found by /code-review on PR #20 (standards axis). G-B3-01: excess 11,254.94 at 6% = 675.30.
def _g_b3_01(charge_cents: int) -> dict[str, Any]:
    return {
        "amount_cents": 2_000_000,
        "free_cents": 874_506,
        "excess_cents": 1_125_494,
        "rate_bp": 600,
        "charge_cents": charge_cents,
        "net_cents": 2_000_000 - charge_cents,
        "contract_year": 3,
        "threshold_tier": "self_service",
        "irs_notice": False,
    }


@pytest.mark.parametrize("charge_cents", [67_529, 67_531, 0, 1_125_495])
def test_issue_22_quote_refuses_a_wrong_charge(charge_cents: int) -> None:
    with pytest.raises(ValidationError):
        Quote.model_validate(_g_b3_01(charge_cents))


def test_issue_22_quote_accepts_the_half_up_charge() -> None:
    Quote.model_validate(_g_b3_01(67_530))


# ---------- #23: intake could overwrite identity-gate-owned session fields ----------
# Found by /code-review on PR #20 (standards axis). Replacing the whole Session would reset
# gate_b_passed, failed_attempts and locked, which only identity_gate may write (D-08).
@pytest.mark.parametrize("node", list(Node))
def test_issue_23_no_node_may_replace_the_whole_session(node: Node) -> None:
    with pytest.raises(ContractViolation):
        check_write(node, "session")


def test_issue_23_session_fields_keep_their_owners() -> None:
    check_write(Node.INTAKE, "session.customer_id")
    check_write(Node.INTAKE, "session.gate_a_trusted")
    for field in ("gate_b_passed", "failed_attempts", "locked"):
        check_write(Node.IDENTITY_GATE, f"session.{field}")
        with pytest.raises(ContractViolation):
            check_write(Node.INTAKE, f"session.{field}")
