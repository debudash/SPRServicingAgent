import logging

import pytest

from agents.tools.registry import ToolRegistry
from contracts.state import ContractViolation
from contracts.tools import TOOL_SCOPE, Role, ToolName


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name in ToolName:
        reg.register(name, lambda n=name, **kw: (n, kw))
    return reg


ALLOWED = [(r, t) for r in Role for t in TOOL_SCOPE[r]]
REFUSED = [(r, t) for r in Role for t in ToolName if t not in TOOL_SCOPE[r]]


@pytest.mark.parametrize(("role", "tool"), ALLOWED)
def test_role_can_call_its_tools(role: Role, tool: ToolName) -> None:
    assert _registry().call(role, tool, x=1) == (tool, {"x": 1})


@pytest.mark.parametrize(("role", "tool"), REFUSED)
def test_role_refused_other_tools(
    role: Role, tool: ToolName, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING), pytest.raises(ContractViolation):
        _registry().call(role, tool)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert role.value in warnings[0].getMessage()
    assert tool.value in warnings[0].getMessage()


def test_concierge_refused_all_tools() -> None:
    assert TOOL_SCOPE[Role.CONCIERGE] == frozenset()
    reg = _registry()
    for tool in ToolName:
        with pytest.raises(ContractViolation):
            reg.call(Role.CONCIERGE, tool)


def test_no_execute_tool() -> None:
    assert "execute" not in {t.value for t in ToolName}
    with pytest.raises(ContractViolation):
        _registry().call(Role.TRANSACTION, "execute")  # type: ignore[arg-type]


def test_register_outside_toolname_is_error() -> None:
    with pytest.raises(ValueError):
        ToolRegistry().register("execute", lambda: None)  # type: ignore[arg-type]
