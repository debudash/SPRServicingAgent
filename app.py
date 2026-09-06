"""Streamlit UI for the SPR Financials servicing agent — a demo + teaching surface.

Pick a customer (starts the session), pick a model, and chat. The right-hand trace
shows each Thought / Action / Observation, the tool's tier, and its source (KB vs
account). Log in as Raymond (SPR-1002, unverified) and ask for his balance to see the
verification gate; ask any verified customer to withdraw to see the confirm-first flow.

Run:  streamlit run app.py   (after: python -m data.ingest)
"""
import streamlit as st
from langchain_core.messages import HumanMessage

from agent import guardrails, identity, react_agent
from data import accounts
from llm import model_names

st.set_page_config(page_title="SPR Servicing Agent", page_icon="🏦", layout="wide")

TIER_COLOR = {guardrails.TIER_1: "#2E7D5B", guardrails.TIER_2: "#1F6FB2",
              guardrails.TIER_3: "#A9432B", guardrails.HANDOFF: "#7A5AA6"}


def render_trace(trace):
    for kind, payload in trace:
        if kind == "thought":
            st.markdown(f"🧠 **Thought** — {payload}")
        elif kind == "action":
            tier = payload["tier"]
            color = TIER_COLOR.get(tier, "#566372")
            st.markdown(f"🛠️ **Action** — `{payload['tool']}` "
                        f"<span style='background:{color};color:#fff;padding:1px 7px;"
                        f"border-radius:9px;font-size:11px'>{guardrails.TIER_LABEL[tier]}</span> "
                        f"{payload['args']}", unsafe_allow_html=True)
        elif kind == "observation":
            st.code(payload, language="text")
        elif kind == "stop":
            st.warning(f"⛔ Guardrail: {payload}")


def chat_page():
    ids = accounts.all_customer_ids()
    labels = {cid: f"{cid} · {accounts.get_account(cid)['name']} "
                   f"({'verified' if accounts.get_account(cid)['identity_verified'] else 'UNVERIFIED'})"
              for cid in ids}
    # Both start unselected: a session belongs to a customer, and nothing should be
    # logged in until someone chooses one.
    with st.sidebar:
        st.header("SPR Servicing Agent")
        cid = st.selectbox("Customer (session)", [None] + ids,
                           format_func=lambda c: labels[c] if c else "— none —")
        model = st.selectbox("Model", [None] + model_names(),
                             format_func=lambda m: m if m else "— none —")
        st.caption("Try: “What's my balance?”, “What's the charge to withdraw $20,000?”, "
                   "then “withdraw $20,000”. Log in as the UNVERIFIED customer to see the gate.")
        if st.button("Reset conversation"):
            st.session_state.pop("history", None); st.session_state.pop("messages", None)

    ready = bool(cid and model)

    if st.session_state.get("ctx") != (cid, model):
        st.session_state.ctx = (cid, model)
        st.session_state.history = []
        st.session_state.messages = []
        if ready:
            # login first: new_messages() reads the session's identity state.
            identity.login(cid)  # once per session, not per turn — verification should persist across messages
            st.session_state.messages = react_agent.new_messages()
        else:
            identity.logout()

    st.title("SPR Financials — Servicing Agent")
    st.caption(f"Session: **{labels[cid] if cid else 'none'}** · model **{model or 'none'}**")

    if not ready:
        missing = " and ".join(x for x in ("a customer" if not cid else "",
                                           "a model" if not model else "") if x)
        st.info(f"Select {missing} in the sidebar to start a session.")

    for turn in st.session_state.get("history", []):
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            if turn.get("trace"):
                with st.expander("Under the hood — reasoning trace"):
                    render_trace(turn["trace"])

    prompt = st.chat_input("Ask about the product, your account, or a withdrawal…",
                           disabled=not ready)
    if not prompt:
        return

    st.session_state.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.messages.append(HumanMessage(prompt))
    with st.chat_message("assistant"):
        try:
            with st.spinner(f"{model} is working…"):
                answer, trace, _tools, _usage = react_agent.run_turn(st.session_state.messages, model)
        except Exception as e:
            answer, trace = (f"Something went wrong ({e}). Check the API key for '{model}' in .env."), []
        st.markdown(answer)
        if trace:
            with st.expander("Under the hood — reasoning trace", expanded=True):
                render_trace(trace)
    st.session_state.history.append({"role": "assistant", "content": answer, "trace": trace})


PAGES = [
    st.Page(chat_page, title="Agent app", icon="🏦", default=True),
    st.Page("pages/1_Behaviour_demo.py", title="Behaviour demo", icon="🧪"),
]

st.navigation(PAGES).run()
