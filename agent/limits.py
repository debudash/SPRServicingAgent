"""Runtime guardrails against loops and cost overruns (enforced by the agent loop).

Model-agnostic, so they apply to every benchmarked model and no provider can run
away with cost. Caps: a step budget per turn, repeated-identical-call detection
(no-progress stop), and a consecutive-failure circuit-breaker.

The no-progress check compares against only the immediately preceding call, not
every call this turn — an intervening different call (e.g. verify_identity fixing
a precondition) means the next identical call is a legitimate retry, not a loop.
"""
import json

import config


def _key(tool_name, args):
    try:
        return tool_name + "|" + json.dumps(args, sort_keys=True, default=str)
    except Exception:
        return tool_name + "|" + str(args)


class LoopGuard:
    def __init__(self, max_steps=None, max_consecutive_failures=None):
        self.max_steps = max_steps or config.MAX_AGENT_STEPS
        self.max_consecutive_failures = max_consecutive_failures or config.MAX_CONSECUTIVE_FAILURES
        self.steps = 0
        self._last_key = None
        self._consecutive_failures = 0

    def before_call(self, tool_name, args):
        self.steps += 1
        if self.steps > self.max_steps:
            return f"stopped: step budget exceeded ({self.max_steps} tool calls)"
        key = _key(tool_name, args)
        if key == self._last_key:
            return "stopped: no progress (repeated identical tool call)"
        self._last_key = key
        return None

    def after_call(self, failed):
        self._consecutive_failures = self._consecutive_failures + 1 if failed else 0
        if self._consecutive_failures >= self.max_consecutive_failures:
            return f"stopped: {self.max_consecutive_failures} consecutive tool failures"
        return None
