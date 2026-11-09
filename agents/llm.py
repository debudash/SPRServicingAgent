"""The one place model calls are built: the model map and prompt assembly."""

from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from contracts.tools import Role

MODELS_PATH = Path(__file__).parent / "config" / "models.yaml"

Effort = Literal["low", "medium", "high"]


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    effort: Effort


@cache
def load_model_map() -> dict[Role, ModelSpec]:
    raw = yaml.safe_load(MODELS_PATH.read_text(encoding="utf-8"))
    return {Role(k): ModelSpec.model_validate(v) for k, v in raw.items()}


def chat_model(role: Role) -> ChatAnthropic:
    """Chat model for a role. No temperature: these models reject it."""
    spec = load_model_map()[role]
    return ChatAnthropic(model_name=spec.model, effort=spec.effort)  # type: ignore[call-arg]


def build_messages(
    system_text: str,
    session_context: str,
    transcript: Sequence[BaseMessage],
) -> list[BaseMessage]:
    """Stable-first order: system (cache breakpoint), session context, conversation.

    The caller must keep dates, times and conversation IDs out of system_text.
    """
    system = SystemMessage(
        content=cast(
            Any,
            [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        )
    )
    return [system, HumanMessage(content=session_context), *transcript]
