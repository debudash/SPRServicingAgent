"""Behaviour demo as a page — the same six scenarios as `python -m scripts.demo`.

The scenarios and their checks live in scripts/demo.py and are imported here, so the
terminal run and this page can never drift apart. Nothing is re-implemented; this page
only renders what scripts.demo.execute() returns.

Page config and navigation live in app.py (st.navigation), so this file must not
call st.set_page_config itself.

Run:  streamlit run app.py   -> "Behaviour demo" in the sidebar
"""
import streamlit as st

from agent import guardrails
from data import retriever
from llm import model_names
from scripts.demo import SCENARIOS, execute

TIER_COLOR = {guardrails.TIER_1: "#2E7D5B", guardrails.TIER_2: "#1F6FB2",
              guardrails.TIER_3: "#A9432B", guardrails.HANDOFF: "#7A5AA6"}


def chip(text, color, mono=False):
    font = "font-family:monospace;" if mono else ""
    return (f"<span style='background:{color};color:#fff;padding:2px 9px;"
            f"border-radius:9px;font-size:11px;{font}'>{text}</span>")


def render(d):
    """Render one finished scenario."""
    misses = [detail for ok, detail in d["results"] if not ok]
    if not misses:
        badge, color = "PASS", "#2E7D5B"
    elif d["known_gap"]:
        badge, color = "KNOWN GAP", "#D6A419"
    else:
        badge, color = "FAIL", "#A9432B"

    with st.container(border=True):
        head, mark = st.columns([6, 1])
        head.markdown(f"**{d['title']}**")
        mark.markdown(chip(badge, color), unsafe_allow_html=True)
        st.caption(d["why"])

        st.markdown(
            f"{chip(f'{d['name']} · {d['customer']} · year {d['contract_year']} of 7', '#566372')} "
            f"{chip('Gate A ' + ('trusted' if d['gate_a'] else 'NOT trusted'), '#2E7D5B' if d['gate_a'] else '#A9432B')} "
            f"{chip('Gate B ' + ('passed' if d['gate_b'] else 'not passed'), '#2E7D5B' if d['gate_b'] else '#8A6D1F')}",
            unsafe_allow_html=True)

        for t in d["turns"]:
            st.markdown(f"💬 **{t['question']}**")
            if t["actions"]:
                for a in t["actions"]:
                    tier = a["tier"]
                    st.markdown(
                        f"&nbsp;&nbsp;🛠️ `{a['tool']}({a['args'] or ''})` "
                        + chip(guardrails.TIER_LABEL[tier], TIER_COLOR.get(tier, "#566372")),
                        unsafe_allow_html=True)
            else:
                st.markdown("&nbsp;&nbsp;⚠️ _no tools called — answered from the model's own memory_",
                            unsafe_allow_html=True)
            st.info(t["answer"])

        for ok, detail in d["results"]:
            if ok:
                st.markdown(f"✅ {detail}")
            elif d["known_gap"]:
                st.markdown(f"🟡 {detail} — _known gap, see README §7_")
            else:
                st.markdown(f"❌ {detail}")
        st.caption(f"{d['elapsed']:.1f}s · {len(d['tools'])} tool call(s)")


def main():
    st.title("🧪 Behaviour demo")
    st.caption("Six scenarios run against a live model and checked programmatically — "
               "no LLM judge. The same scenarios as `python -m scripts.demo`.")

    with st.sidebar:
        st.header("Behaviour demo")
        names = model_names()
        model = st.selectbox("Model", names,
                             index=names.index("gpt-4o") if "gpt-4o" in names else 0)
        st.caption("Every scenario is a claim the README makes, made visible: the "
                   "identity gates, quote-before-execute, escalation, and the "
                   "grounding gap the evals found.")
        run = st.button("Run the demo", type="primary", use_container_width=True)

    if not run and "demo_results" not in st.session_state:
        st.info("Pick a model and press **Run the demo** in the sidebar. "
                "Takes about 25 seconds.")
        return

    if run:
        with st.spinner("Warming the knowledge-base index…"):
            retriever.search("surrender charge", k=1)   # one-off; keeps timings honest

        results = []
        progress = st.progress(0.0, text="Starting…")
        slot = st.container()
        for i, sc in enumerate(SCENARIOS):
            progress.progress(i / len(SCENARIOS), text=f"Running: {sc['title']}")
            d = execute(sc, model)
            results.append(d)
            with slot:
                render(d)
        progress.empty()
        st.session_state.demo_results = results
    else:
        for d in st.session_state.demo_results:
            render(d)

    results = st.session_state.demo_results
    passed = sum(1 for d in results for ok, _ in d["results"] if ok)
    gaps = sum(1 for d in results if d["known_gap"] for ok, _ in d["results"] if not ok)
    failed = sum(1 for d in results if not d["known_gap"] for ok, _ in d["results"] if not ok)
    elapsed = sum(d["elapsed"] for d in results)

    st.divider()
    a, b, c, e = st.columns(4)
    a.metric("Confirmed", f"{passed} / {passed + gaps + failed}")
    b.metric("Known gaps", gaps)
    c.metric("Unexpected failures", failed)
    e.metric("Agent time", f"{elapsed:.1f}s")
    if failed:
        st.error("A behaviour that should hold did not — see the ❌ lines above.")
    elif gaps:
        st.warning("Known gaps only: the grounding weakness documented in README §7. "
                   "Not a regression.")
    else:
        st.success("Every expected behaviour held.")


main()
