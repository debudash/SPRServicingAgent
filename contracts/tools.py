"""Agent roles, the tools each role may call (FR-22), graph nodes, and the step names
traces and evals use."""

from enum import StrEnum


class Role(StrEnum):
    CONCIERGE = "concierge"
    KNOWLEDGE = "knowledge"
    TRANSACTION = "transaction"
    COMPLIANCE = "compliance"
    CASE = "case"


class ToolName(StrEnum):
    SEARCH_KB = "search_kb"
    GET_ACCOUNT = "get_account"
    QUOTE = "quote"
    PROPOSE = "propose"
    GET_POLICY = "get_policy"
    CREATE_CASE = "create_case"


# Blueprint section 3. The Concierge has no tools (ADR 0005). `execute` is not a tool at
# all: only the execute node runs it, after the approval edge (ADR 0003).
TOOL_SCOPE: dict[Role, frozenset[ToolName]] = {
    Role.CONCIERGE: frozenset(),
    Role.KNOWLEDGE: frozenset({ToolName.SEARCH_KB}),
    Role.TRANSACTION: frozenset({ToolName.GET_ACCOUNT, ToolName.QUOTE, ToolName.PROPOSE}),
    Role.COMPLIANCE: frozenset({ToolName.GET_POLICY}),
    Role.CASE: frozenset({ToolName.CREATE_CASE}),
}


class Node(StrEnum):
    """Graph nodes (blueprint section 2), plus the runner. The writers in FIELD_WRITERS."""

    RUNNER = "runner"
    INTAKE = "intake"
    CONCIERGE = "concierge"
    IDENTITY_GATE = "identity_gate"
    KNOWLEDGE = "knowledge"
    ACCOUNT = "account"
    TRANSACTION = "transaction"
    CONFIRM = "confirm"
    RULES = "rules"
    COMPLIANCE = "compliance"
    APPROVAL = "approval"
    EXECUTE = "execute"
    CASE = "case"
    HUMAN_REVIEW = "human_review"
    RESPOND = "respond"


class Step(StrEnum):
    """Trace step names, used by the eval cases' `tools`, `not_tools` and `order` keys."""

    SEARCH_KB = "search_kb"
    GET_ACCOUNT = "get_account"
    VERIFY_IDENTITY = "verify_identity"
    QUOTE = "quote"
    PROPOSE = "propose"
    GET_POLICY = "get_policy"
    COMPLIANCE_REVIEW = "compliance_review"
    EXECUTE = "execute"
    CREATE_CASE = "create_case"
    HUMAN_APPROVAL = "human_approval"
