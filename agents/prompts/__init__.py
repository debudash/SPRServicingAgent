"""Versioned system prompts. Prompts hold rules only: no dates, IDs or customer data (cacheable)."""

from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).parent


def load(prompt_id: str) -> tuple[str, int]:
    """Return (prompt text without front matter, version) for a prompt ID."""
    raw = (PROMPTS_DIR / f"{prompt_id}.md").read_text(encoding="utf-8")
    parts = raw.split("---\n", 2)
    if len(parts) != 3 or parts[0] != "":
        raise ValueError(f"prompt {prompt_id} has no front matter")
    meta = yaml.safe_load(parts[1])
    if meta.get("prompt_id") != prompt_id:
        raise ValueError(f"prompt file {prompt_id}.md declares prompt_id {meta.get('prompt_id')}")
    return parts[2].strip(), int(meta["version"])
