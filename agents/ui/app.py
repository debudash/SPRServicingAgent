"""Chat UI over the desk runner, with a sidebar that shows why the last turn went as it did.

Anonymous conversations only (B1). Tests inject a fake runner via `st.session_state["runner"]`.
"""

import streamlit as st

from agents.wiring import MissingApiKeyError, build_runner
from contracts.ports import DeskRunner, TurnResult


@st.cache_resource
def _real_runner() -> DeskRunner:
    return build_runner()


def _runner() -> DeskRunner | None:
    if "runner" not in st.session_state:
        try:
            st.session_state["runner"] = _real_runner()
        except MissingApiKeyError:
            return None
    runner: DeskRunner = st.session_state["runner"]
    return runner


def _sidebar(result: TurnResult | None) -> None:
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
        st.session_state["conversation_id"] = runner.start(None)
        st.session_state["messages"] = []
        st.session_state["last_result"] = None

    for m in st.session_state["messages"]:
        with st.chat_message(m["role"]):
            st.write(m["text"])
            if m.get("outcome"):
                st.caption(f"outcome: {m['outcome']}")

    prompt = st.chat_input("Ask about your SecureGrowth annuity")
    if prompt:
        result = runner.send(st.session_state["conversation_id"], prompt)
        st.session_state["messages"] += [
            {"role": "user", "text": prompt},
            {"role": "assistant", "text": result.reply_text, "outcome": result.outcome.value},
        ]
        st.session_state["last_result"] = result
        st.rerun()
    _sidebar(st.session_state["last_result"])


main()
