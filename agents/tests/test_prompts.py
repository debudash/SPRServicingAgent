import re

import pytest

from agents.prompts import PROMPTS_DIR, load

RULES = {
    "concierge": ["GR-08", "GR-11", "GR-15"],
    "knowledge": ["GR-01", "GR-05", "GR-08", "GR-11", "GR-15"],
    "respond": ["GR-10", "GR-20"],
    "compliance": ["GR-08", "GR-11", "GR-19"],
}
# Each prompt's version, pinned: a prompt edit must bump its version (it is in every audit row).
VERSIONS = {"concierge": 6, "knowledge": 1, "respond": 1, "compliance": 1}
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")


@pytest.mark.parametrize("prompt_id", RULES)
def test_prompt_loads_with_version_and_rules(prompt_id: str) -> None:
    text, version = load(prompt_id)
    assert version == VERSIONS[prompt_id]
    assert not text.startswith("---")
    for rule in RULES[prompt_id]:
        assert rule in text


@pytest.mark.parametrize("prompt_id", RULES)
def test_prompt_has_no_date(prompt_id: str) -> None:
    raw = (PROMPTS_DIR / f"{prompt_id}.md").read_text(encoding="utf-8")
    assert not DATE.search(raw)


def test_unknown_prompt_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load("nope")
