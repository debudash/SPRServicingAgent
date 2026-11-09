"""Tool registry: implementations are registered by ToolName; `call` enforces TOOL_SCOPE (FR-22).

Scope is enforced in code, not in prompts. There is no `execute` tool (ADR 0003).
"""

import logging
from collections.abc import Callable
from typing import Any

from contracts.state import ContractViolation
from contracts.tools import TOOL_SCOPE, Role, ToolName

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[ToolName, Callable[..., Any]] = {}

    def register(self, name: ToolName, fn: Callable[..., Any]) -> None:
        """Register `fn` under `name`. Anything that is not a ToolName is an error."""
        if not isinstance(name, ToolName):
            raise ValueError(f"{name!r} is not a ToolName; cannot register it")
        self._tools[name] = fn

    def call(self, role: Role, tool: ToolName, **kwargs: Any) -> Any:
        """Call `tool` for `role` if TOOL_SCOPE allows it, else log a warning and raise."""
        if not isinstance(tool, ToolName) or tool not in TOOL_SCOPE.get(role, frozenset()):
            logger.warning("tool call refused: role=%s tool=%s", role, tool)
            raise ContractViolation(f"role {role} may not call tool {tool}")
        fn = self._tools.get(tool)
        if fn is None:
            raise KeyError(f"tool {tool} is in scope but has no registered implementation")
        return fn(**kwargs)
