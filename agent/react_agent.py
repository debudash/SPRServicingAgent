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
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", b)) if isinstance(b, dict) else str(b) for b in content)
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


def new_messages():
    return [SystemMessage(SYSTEM_PROMPT)]


def run(user_message, model_name="claude", customer_id=None):
    """Single-turn wrapper (used by the eval harness). Logs in the customer so tools
    are scoped + verification state is set, then answers one message."""
    if customer_id:
        identity.login(customer_id)
    messages = new_messages() + [HumanMessage(user_message)]
    answer, trace, tools_called, usage = run_turn(messages, model_name)
    return {"answer": answer, "trace": trace, "tools_called": tools_called,
            "usage": usage, "messages": messages,
            "steps": sum(1 for k, _ in trace if k == "action")}
