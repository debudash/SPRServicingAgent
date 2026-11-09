# 0003. LangGraph, with a code-routed graph and a fixed money path

Date: 2026-11-09 · Status: accepted · Decided by: integrator (owner) · Issue: #15

## Context
The desk needs several agents sharing one conversation, a pause for a human reviewer that may last hours, and a
money path that must never be skipped (PRD FR-08, FR-11). The platform audit found that orchestration
frameworks provide state and routing but do not enforce field ownership, tool scope, approval binding,
idempotency or budgets (PRD PG-08), so those are ours either way. The choice is what carries the case and
who decides the next step.

## Decision
- **Framework: LangGraph.** A graph of nodes over one typed conversation state, with checkpointing per conversation and
  `interrupt` for the human-review pause. LLM calls go through `ChatAnthropic` so LangSmith traces them.
- **Topology: code-routed.** The Concierge (an LLM) classifies intent. Every edge after that is a Python
  function of the conversation state. The money path is a fixed sequence: quote → confirm → rules → Compliance →
  approval → execute, or a case for a human. LLMs judge inside a node; they never choose the next node.
- **Authority stays in code.** The approval token is issued by code, only when Compliance says `approve`
  and the rule engine raised no flag. `execute` is a node, not a tool any agent can call.

## Consequences
- The routing can be unit-tested with a scripted model: every path through the graph is a test, and the
  money path's order is a property of the graph, not of a prompt.
- Safety does not depend on a model following instructions to call Compliance. A model that misbehaves
  can produce a bad answer, but not an unreviewed withdrawal.
- Flexibility is lower: a new intent means a new edge in code, reviewed like any money-path change.
- LangGraph becomes a core dependency and the integrator owns its version.

## Alternatives rejected
- **Plain Anthropic SDK with our own state machine.** No hidden framework, but we would write
  checkpointing and resume for the human pause ourselves.
- **LangChain agents chained in code (the v1 style).** No shared state and no interrupt, so the human
  pause would be hand-built.
- **An LLM supervisor choosing the next agent.** A model could route around Compliance; safety would then
  rest on every tool guarding itself.
- **Peer handoffs between agents.** Hardest to reason about and to audit.
