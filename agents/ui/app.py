"""The desk's UI: a login page, the chat, the step-up form (ADR 0007) and the review queue (B4).

The login page stands in for upstream authentication: a customer dropdown and a password, or
"Continue without logging in" for product questions. In the chat, the sidebar shows why the last
turn went as it did and the customer's cases (FR-18). When a withdrawal needs the step-up check, a
masked form appears outside the chat; its values go to `runner.step_up` and are never shown or
sent as a message. The review queue is the human reviewer's page (FR-17, #146): a person reads the
case packet and approves, rejects or asks for information; an approval executes through the same
guarded path as the desk's own. The behaviour demo (#104) plays nine scenarios through the real
desk with scripted models, offline, and shows which guard decided each one.
Tests inject fakes via `st.session_state["runner"]` and `st.session_state["review"]`.
"""

from datetime import date

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from agents.demo.scenarios import SCENARIOS, ScenarioRun, run_all, run_scenario
from agents.wiring import MissingApiKeyError, build_desk, customer_names
from contracts.messages import (
    CASE_DECIDABLE,
    CasePacket,
    CaseReason,
    CaseStatus,
    Decision,
    HumanDecision,
)
from contracts.money import format_dollars
from contracts.outcomes import Outcome
from contracts.ports import LoginDeskRunner, LoginRefused, ReviewDesk, TurnResult

STEP_UP_SHOWN = "Identity check submitted"
_CHAT_KEYS = ("conversation_id", "who", "messages", "last_result", "customer_id")


@st.cache_resource
def _real_desk() -> tuple[LoginDeskRunner, ReviewDesk]:
    return build_desk()


def _runner() -> LoginDeskRunner | None:
    if "runner" not in st.session_state:
        try:
            st.session_state["runner"], st.session_state["review"] = _real_desk()
        except MissingApiKeyError:
            return None
    runner: LoginDeskRunner = st.session_state["runner"]
    return runner


def _review() -> ReviewDesk | None:
    review: ReviewDesk | None = st.session_state.get("review")
    return review


def _open_chat(conversation_id: str, who: str) -> None:
    st.session_state["conversation_id"] = conversation_id
    st.session_state["who"] = who
    st.session_state["messages"] = []
    st.session_state["last_result"] = None


def _login_page(runner: LoginDeskRunner) -> None:
    st.subheader("Log in")
    st.caption("Simulated upstream login (demo passwords are in data/README.md).")
    names = customer_names()
    customer = st.selectbox(
        "Customer",
        list(names),
        format_func=lambda c: f"{c} · {names[c]}",
        key="login_customer",
    )
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Log in", key="login_submit", type="primary"):
        result = runner.login(str(customer), password)
        if isinstance(result, LoginRefused):
            st.error("That customer and password don't match. Please try again.")
        else:
            _open_chat(result, f"Logged in as {customer}")
            st.session_state["customer_id"] = str(customer)
            st.rerun()
    st.divider()
    if st.button("Continue without logging in", key="guest"):
        _open_chat(runner.start(None), "Guest (product questions only)")
        st.rerun()
    st.divider()
    st.caption("SPR staff")
    left, right = st.columns(2)
    if _review() is not None and left.button("Open the review queue", key="open_review"):
        st.session_state["view"] = "review"
        st.rerun()
    _demo_button(right)


def _demo_button(where: DeltaGenerator) -> None:
    if where.button("Open the behaviour demo", key="open_demo"):
        st.session_state["view"] = "demo"
        st.rerun()


def _sidebar(result: TurnResult | None) -> None:
    st.sidebar.markdown(f"**{st.session_state['who']}**")
    if st.sidebar.button("Log out", key="logout"):
        for key in _CHAT_KEYS:
            st.session_state.pop(key, None)
        st.rerun()
    _your_cases()
    st.sidebar.header("Why it answered this way")
    if result is None:
        st.sidebar.write("Send a message to see the turn's details.")
        return
    st.sidebar.markdown(f"**Outcome:** `{result.outcome.value}`")
    if result.reference:
        st.sidebar.markdown(f"**Reference:** `{result.reference}`")
    st.sidebar.markdown("**Citations**")
    for c in result.citations:
        st.sidebar.write(f"{c.doc_id} v{c.version} — {c.section}")
    if not result.citations:
        st.sidebar.write("none")
    st.sidebar.markdown("**Nodes:** " + (" → ".join(n.value for n in result.nodes) or "none"))
    st.sidebar.markdown("**Steps:** " + (", ".join(s.value for s in result.steps) or "none"))
    u = result.usage
    st.sidebar.markdown(
        f"**Cost:** ${u.cost_micros / 1_000_000:.4f} "
        f"({u.input_tokens} in / {u.output_tokens} out tokens, {result.latency_ms} ms)"
    )


def _label(reason: CaseReason) -> str:
    return reason.value.replace("_", " ")


def _your_cases() -> None:
    """FR-18: the customer sees where each of their cases stands, including a reviewer's
    decision made after the conversation."""
    review, customer = _review(), st.session_state.get("customer_id")
    if review is None or customer is None:
        return
    cases = review.queue(customer_id=customer)
    if not cases:
        return
    st.sidebar.header("Your cases")
    for c in cases:
        st.sidebar.write(f"{c.case_id}: {_label(c.opened_for)} ({c.status.value})")


def _record(customer_text: str, result: TurnResult) -> None:
    st.session_state["messages"] += [
        {"role": "user", "text": customer_text},
        {"role": "assistant", "text": result.reply_text, "outcome": result.outcome.value},
    ]
    st.session_state["last_result"] = result


def _step_up_form(runner: LoginDeskRunner) -> None:
    """ADR 0007: the masked step-up form, outside the chat. Its values go only to `step_up`."""
    with st.container(border=True):
        st.markdown("**Confirm it's you before the withdrawal goes ahead**")
        dob = st.date_input(
            "Date of birth",
            value=None,
            min_value=date(1900, 1, 1),
            max_value=date.today(),
            key="step_up_dob",
        )
        last4 = st.text_input(
            "Last four digits of your SSN", type="password", max_chars=4, key="step_up_last4"
        )
        if st.button("Confirm", key="step_up_submit", type="primary"):
            if dob is None or len(last4) != 4 or not last4.isdigit():
                st.warning("Please give your date of birth and the four digits.")
                return
            result = runner.step_up(st.session_state["conversation_id"], dob, last4)
            _record(STEP_UP_SHOWN, result)
            for key in ("step_up_dob", "step_up_last4"):  # the values do not linger
                st.session_state.pop(key, None)
            st.rerun()


def _chat(runner: LoginDeskRunner) -> None:
    for m in st.session_state["messages"]:
        with st.chat_message(m["role"]):
            st.write(m["text"])
            if m.get("outcome"):
                st.caption(f"outcome: {m['outcome']}")
    last: TurnResult | None = st.session_state["last_result"]
    if last is not None and last.step_up_required:
        _step_up_form(runner)
    prompt = st.chat_input("Ask about your SecureGrowth annuity")
    if prompt:
        _record(prompt, runner.send(st.session_state["conversation_id"], prompt))
        st.rerun()
    _sidebar(last)


# ---------- B4: the review queue (FR-16, FR-17, #146) ----------
_FILTERS = {
    "Waiting for a decision": (CaseStatus.OPEN, CaseStatus.INFO_REQUESTED),
    "Approved": (CaseStatus.APPROVED,),
    "Rejected": (CaseStatus.REJECTED,),
    "All": tuple(CaseStatus),
}


def _packet_view(packet: CasePacket) -> None:
    st.markdown(f"**Request:** {packet.request_summary}")
    q = packet.quote
    if q is not None:
        st.markdown("**Quote the customer saw**")
        st.table(
            {
                "Gross": [format_dollars(q.amount_cents)],
                "Free": [format_dollars(q.free_cents)],
                "Excess": [format_dollars(q.excess_cents)],
                "Rate": [f"{q.rate_bp / 100:g}%"],
                "Charge": [format_dollars(q.charge_cents)],
                "Net": [format_dollars(q.net_cents)],
                "Tier": [q.threshold_tier.value],
                "IRS notice": ["yes" if q.irs_notice else "no"],
            }
        )
    if packet.rule_flags:
        flags = ", ".join(sorted(f.value for f in packet.rule_flags))
        st.markdown(f"**Rule flags (code):** {flags}")
    if packet.compliance_decision is not None:
        st.markdown(f"**Compliance agent:** {packet.compliance_decision.value}")
        for r in packet.compliance_reasons:
            st.write(f"- {r.text} ({r.policy_ref})")
    if packet.signals:
        st.markdown("**Signals:** " + ", ".join(sorted(s.value for s in packet.signals)))
    st.markdown(f"**Conversation excerpt (restricted fields removed):** {packet.excerpt}")
    st.markdown(f"**Recommendation:** {packet.recommendation}")


def _review_page(review: ReviewDesk) -> None:
    st.subheader("Review queue")
    st.caption(
        "A person decides every case here. Approving a withdrawal executes it through the same "
        "guarded path as the desk: a token bound to this exact proposal, then the ledger once."
    )
    if st.button("Back to the login page", key="close_review"):
        st.session_state.pop("view", None)
        st.rerun()
    reviewer = st.text_input("Your reviewer ID", value="reviewer", key="reviewer_id")
    shown = st.radio("Show", list(_FILTERS), horizontal=True, key="review_filter")
    wanted = _FILTERS[str(shown)]
    cases = [c for c in review.queue() if c.status in wanted]
    if not cases:
        st.info("No cases here.")
    for c in cases:
        title = f"{c.case_id} · {c.customer_id} · {_label(c.opened_for)} · {c.status.value}"
        with st.expander(title, expanded=c.status in CASE_DECIDABLE):
            packet = review.case(c.case_id)
            if packet is not None:
                _packet_view(packet)
            if c.decided_by:
                st.caption(f"Decided by {c.decided_by}")
            if c.status not in CASE_DECIDABLE:
                continue
            left, middle, right = st.columns(3)
            for column, decision, label in (
                (left, Decision.APPROVE, "Approve"),
                (middle, Decision.REJECT, "Reject"),
                (right, Decision.REQUEST_INFO, "Request information"),
            ):
                if column.button(label, key=f"{decision.value}-{c.case_id}"):
                    try:
                        result = review.decide(
                            HumanDecision(
                                case_id=c.case_id,
                                reviewer_id=(reviewer or "reviewer").strip(),
                                decision=decision,
                            )
                        )
                        shown_result = (result.outcome, result.text)
                    except ValueError as refused:  # #155: a bad reviewer ID, or decided meanwhile
                        shown_result = (Outcome.NOT_PERMITTED, str(refused))
                    st.session_state["review_result"] = shown_result
                    st.rerun()
    last = st.session_state.pop("review_result", None)
    if last is not None:
        outcome, text = last
        done = outcome in (Outcome.EXECUTED, Outcome.ANSWERED)
        (st.success if done else st.warning)(f"{outcome.value}: {text}")


# ---------- #104: the behaviour demo ----------
_TITLES = {f"{s.number}. {s.title}": s for s in SCENARIOS}


def _demo_page() -> None:
    st.subheader("Behaviour demo")
    st.caption(
        "Nine conversations played through the real desk: the graph, the SQLite stores, the "
        "approval store, the ledger, the audit log and the review queue, each over a fresh "
        "scratch database. Only the models are scripted (offline: no API key, same result every "
        "time), so what you see deciding is the code guards."
    )
    if st.button("Back to the login page", key="close_demo"):
        st.session_state.pop("view", None)
        st.rerun()
    runs: dict[int, ScenarioRun] = st.session_state.setdefault("demo_runs", {})
    if st.button("Run all nine", key="demo_run_all"):
        with st.spinner("Running all nine scenarios..."):
            runs.update({r.scenario.number: r for r in run_all()})
    if runs:
        st.table(
            {
                "#": [n for n in sorted(runs)],
                "Scenario": [runs[n].scenario.title for n in sorted(runs)],
                "Outcome": [runs[n].outcome for n in sorted(runs)],
                "Executed": [runs[n].executions for n in sorted(runs)],
                "Result": ["PASS" if runs[n].passed else "FAIL" for n in sorted(runs)],
            }
        )
    st.divider()
    chosen = _TITLES[str(st.selectbox("Scenario", list(_TITLES), key="demo_scenario"))]
    st.markdown(f"**What happens:** {chosen.story}")
    st.info(f"**The guard:** {chosen.guard}")
    if st.button("Run", key="demo_run", type="primary"):
        with st.spinner("Running..."):
            runs[chosen.number] = run_scenario(chosen)
    run = runs.get(chosen.number)
    if run is not None:
        _demo_card(run)


def _plain(text: str) -> str:
    """Dollar amounts as text: markdown would read a pair of `$` as a formula."""
    return text.replace("$", "\\$")


def _demo_card(run: ScenarioRun) -> None:
    s = run.scenario
    with st.container(border=True):
        verdict = "PASS" if run.passed else "FAIL"
        who = s.customer or "a guest"
        st.markdown(
            f"**{s.number}. {s.title}** · {who} · outcome `{run.outcome}` · "
            f"executed {run.executions} · **{verdict}** ({run.elapsed_ms} ms)"
        )
        for f in run.failures:
            st.error(f)
        for t in run.turns:
            asker = "user" if t.who == "Customer" else t.who
            with st.chat_message(asker):
                st.markdown(_plain(t.said))
            with st.chat_message("assistant"):
                st.markdown(_plain(t.reply))
                facts = [f"outcome: {t.outcome}"]
                if t.reference:
                    facts.append(f"reference: {t.reference}")
                if t.citations:
                    facts.append("cites: " + "; ".join(t.citations))
                st.caption(" · ".join(facts))
                if t.nodes:
                    st.caption("nodes: " + " → ".join(t.nodes))
                if t.steps:
                    st.caption("tools: " + ", ".join(t.steps))
        st.markdown("**Ledger (transactions)**")
        if run.ledger:
            st.table([vars(row) for row in run.ledger])
        else:
            st.write("No money moved.")
        st.markdown("**Audit log**")
        st.dataframe(
            [
                {"turn": a.turn, "node": a.node, "event": a.event, "details": a.payload}
                for a in run.audit
            ],
            hide_index=True,
        )


def main() -> None:
    st.set_page_config(page_title="SPR Withdrawal & Hardship Desk")
    st.title("Withdrawal & Hardship Case Desk")
    if st.session_state.get("view") == "demo":  # offline: needs no API key (#104)
        _demo_page()
        return
    runner = _runner()
    if runner is None:
        st.error(
            "ANTHROPIC_API_KEY is not set. Add it to a `.env` file in the repo root "
            "(or export it) and restart the desk."
        )
        _demo_button(st.container())
        return
    review = _review()
    if st.session_state.get("view") == "review" and review is not None:
        _review_page(review)
        return
    if "conversation_id" not in st.session_state:
        _login_page(runner)
        return
    _chat(runner)


main()
