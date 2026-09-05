"""The primary agent — a legible, model-swappable tool-calling loop.

The same loop runs on GPT-4o / Gemini / Claude via llm.get_model, so the benchmark
compares models fairly. It captures a Thought/Action/Observation trace, tracks token
usage (for the cost metric) and which tools ran (for safety scoring), scopes tools to
the authenticated customer, and enforces LoopGuard so it always terminates.

Public API: run(user_message, model_name="claude", customer_id=None) -> dict
"""
from langchain_core.messages import (AIMessage, HumanMessage, SystemMessage,
                                     ToolMessage)

from agent import guardrails, identity, limits
from agent.prompts import SYSTEM_PROMPT
from agent.tools import ALL_TOOLS
from llm import get_model

_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


def _text(content) -> str:
    """Extract visible text, skipping non-text blocks (e.g. Claude's mandatory
    'thinking' block, which has no 'text' key and would otherwise dump its raw
    signature payload into the answer)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if "text" in b:
                    parts.append(str(b["text"]))
            else:
                parts.append(str(b))
        return " ".join(parts)
    return str(content)


def _add_usage(total, ai):
    u = getattr(ai, "usage_metadata", None) or {}
    total["input_tokens"] += u.get("input_tokens", 0) or 0
    total["output_tokens"] += u.get("output_tokens", 0) or 0


def _exec_tool(name, args):
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return f"[ERROR] unknown tool '{name}'", True
    try:
        return str(tool.invoke(args or {})), False
    except Exception as e:
        return f"[ERROR] {name} failed: {e}", True


def run_turn(messages, model_name):
    guard = limits.LoopGuard()
    trace, tools_called = [], []
    usage = {"input_tokens": 0, "output_tokens": 0}
    llm = get_model(model_name).bind_tools(ALL_TOOLS)

    while True:
        ai = llm.invoke(messages)
        messages.append(ai)
        _add_usage(usage, ai)
        if _text(ai.content).strip():
            trace.append(("thought", _text(ai.content).strip()))

        if not ai.tool_calls:
            return _text(ai.content).strip(), trace, tools_called, usage

        answered = set()

        def _finalize(reason, tripped_id):
            for p in ai.tool_calls:
                if p["id"] not in answered:
                    note = reason if p["id"] == tripped_id else "skipped: turn limit reached"
                    messages.append(ToolMessage(note, tool_call_id=p["id"]))
                    answered.add(p["id"])
            trace.append(("stop", reason))
            final = llm.invoke(messages)
            messages.append(final)
            _add_usage(usage, final)
            return (_text(final.content).strip() or reason), trace, tools_called, usage

        for tc in ai.tool_calls:
            name, args, tc_id = tc["name"], tc.get("args", {}), tc["id"]
            stop = guard.before_call(name, args)
            if stop:
                return _finalize(stop, tc_id)

            result, failed = _exec_tool(name, args)
            tools_called.append(name)
            trace.append(("action", {"tool": name, "args": args, "tier": guardrails.tier_of(name)}))
            trace.append(("observation", result))
            messages.append(ToolMessage(result, tool_call_id=tc_id))
            answered.add(tc_id)

            fstop = guard.after_call(failed)
            if fstop:
                return _finalize(fstop, tc_id)


def _session_context() -> str:
    """Gate A is known the moment the session starts, so the agent is told up front
    rather than discovering it by trial. Without this, an unverified customer gets
    asked for a DOB and SSN that can never help them."""
    if identity.account_is_trusted():
        if identity.challenge_passed():
            return ("SESSION: SPR has verified this customer's identity on record, and the "
                    "caller has already passed this session's identity challenge. Use the "
                    "account tools directly — do not ask them to verify again.")
        return ("SESSION: SPR has verified this customer's identity on record (Gate A "
                "passed). As of the start of this session the caller has NOT yet passed "
                "the date-of-birth + last-4-SSN challenge — ask for those and call "
                "verify_identity before sharing account details or touching a withdrawal. "
                "Once a verify_identity call in this conversation returns [VERIFIED], that "
                "stands for the rest of the session; do not ask for them again.")
    return ("SESSION: SPR has NOT verified this customer's identity on record (Gate A "
            "failed). You cannot act on this account at all, and no credentials can "
            "change that here. Do NOT ask for their date of birth or SSN. Tell them our "
            "records show the account hasn't completed SPR's identity verification, so "
            "you can't establish their identity or act on the account, and they need to "
            "verify directly with SPR first. You can still answer general product "
            "questions from the knowledge base.")


def new_messages():
    """Call AFTER identity.login() — the session context depends on it."""
    return [SystemMessage(SYSTEM_PROMPT), SystemMessage(_session_context())]


def run(user_message, model_name="claude", customer_id=None, challenge_passed=False):
    """Single-turn wrapper (used by the eval harness). Logs in the customer so tools
    are scoped, then answers one message.

    challenge_passed models a caller who already cleared this session's DOB/SSN
    challenge (Gate B) earlier in the call, so a case can measure something other
    than identity. It CANNOT grant access on its own: account trust (Gate A) is read
    from the record, so an account SPR hasn't verified stays blocked regardless.
    """
    if customer_id:
        identity.login(customer_id)
        if challenge_passed:
            identity.mark_verified()
    messages = new_messages() + [HumanMessage(user_message)]
    answer, trace, tools_called, usage = run_turn(messages, model_name)
    return {"answer": answer, "trace": trace, "tools_called": tools_called,
            "usage": usage, "messages": messages,
            "steps": sum(1 for k, _ in trace if k == "action")}
