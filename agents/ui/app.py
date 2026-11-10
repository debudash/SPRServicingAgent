"""The desk's UI: a login page, the chat, and the step-up form (ADR 0007).

The login page stands in for upstream authentication: a customer dropdown and a password, or
"Continue without logging in" for product questions. In the chat, the sidebar shows why the last
turn went as it did. When a withdrawal needs the step-up check, a masked form appears outside the
chat; its values go to `runner.step_up` and are never shown or sent as a message.
Tests inject a fake runner via `st.session_state["runner"]`.
"""

from datetime import date

import streamlit as st

from agents.wiring import MissingApiKeyError, build_runner, customer_ids
from contracts.ports import LoginDeskRunner, LoginRefused, TurnResult

STEP_UP_SHOWN = "Identity check submitted"
_CHAT_KEYS = ("conversation_id", "who", "messages", "last_result")


@st.cache_resource
def _real_runner() -> LoginDeskRunner:
    return build_runner()


def _runner() -> LoginDeskRunner | None:
    if "runner" not in st.session_state:
        try:
            st.session_state["runner"] = _real_runner()
        except MissingApiKeyError:
            return None
    runner: LoginDeskRunner = st.session_state["runner"]
    return runner


def _open_chat(conversation_id: str, who: str) -> None:
    st.session_state["conversation_id"] = conversation_id
    st.session_state["who"] = who
    st.session_state["messages"] = []
    st.session_state["last_result"] = None


def _login_page(runner: LoginDeskRunner) -> None:
    st.subheader("Log in")
    st.caption("Simulated upstream login (demo passwords are in data/README.md).")
    customer = st.selectbox("Customer", customer_ids(), key="login_customer")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Log in", key="login_submit", type="primary"):
        result = runner.login(str(customer), password)
        if isinstance(result, LoginRefused):
            st.error("That customer and password don't match. Please try again.")
        else:
            _open_chat(result, f"Logged in as {customer}")
            st.rerun()
    st.divider()
    if st.button("Continue without logging in", key="guest"):
        _open_chat(runner.start(None), "Guest (product questions only)")
        st.rerun()


def _sidebar(result: TurnResult | None) -> None:
    st.sidebar.markdown(f"**{st.session_state['who']}**")
    if st.sidebar.button("Log out", key="logout"):
        for key in _CHAT_KEYS:
            st.session_state.pop(key, None)
        st.rerun()
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


def main() -> None:
    st.set_page_config(page_title="SPR Withdrawal & Hardship Desk")
    st.title("Withdrawal & Hardship Case Desk")
    runner = _runner()
    if runner is None:
        st.error(
            "ANTHROPIC_API_KEY is not set. Add it to a `.env` file in the repo root "
            "(or export it) and restart the desk."
        )
        return
    if "conversation_id" not in st.session_state:
        _login_page(runner)
        return
    _chat(runner)


main()
