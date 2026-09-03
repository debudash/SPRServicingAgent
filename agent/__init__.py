# agent package.
# identity.py   -> session: who the customer is + whether identity is verified
# tools.py      -> the 6 servicing tools (grouped by risk tier)
# withdrawal.py -> pure surrender-charge math (ground truth)
# guardrails.py -> tier model + gating
# limits.py     -> LoopGuard (loop/cost caps)
# prompts.py    -> system prompt
# react_agent.py-> the model-swappable tool-calling loop
