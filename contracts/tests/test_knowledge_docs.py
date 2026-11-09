"""Checks on the integrator-owned knowledge documents (knowledge/README.md)."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "knowledge"
STARTER = ROOT / "problemstmt" / "spr_starter_kit" / "knowledge_base"
DOCS = sorted(p for p in KNOWLEDGE.glob("*.md") if p.name != "README.md")
REQUIRED = {"doc_id", "version", "effective_date", "synthetic", "source"}


def _split(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} has no front matter"
    _, front, body = text.split("---\n", 2)
    meta: dict[str, Any] = yaml.safe_load(front)
    return meta, body.removeprefix("\n")


@pytest.mark.parametrize("path", DOCS, ids=[p.stem for p in DOCS])
def test_front_matter(path: Path) -> None:
    meta, body = _split(path)
    assert REQUIRED <= set(meta), f"missing: {REQUIRED - set(meta)}"
    assert meta["doc_id"] == path.stem
    assert isinstance(meta["version"], int) and meta["version"] >= 1
    assert isinstance(meta["effective_date"], date)
    assert isinstance(meta["synthetic"], bool)
    assert body.strip()


def test_starter_documents_are_unchanged_below_the_front_matter() -> None:
    for source in STARTER.glob("*.md"):
        meta, body = _split(KNOWLEDGE / source.name)
        assert meta["synthetic"] is False
        assert body == source.read_text(encoding="utf-8"), source.name


def test_every_document_not_from_the_starter_kit_is_marked_synthetic() -> None:
    starter = {p.name for p in STARTER.glob("*.md")}
    for path in DOCS:
        if path.name not in starter:
            assert _split(path)[0]["synthetic"] is True, path.name


def test_the_new_policies_restate_the_owner_decisions() -> None:
    large = (KNOWLEDGE / "large_withdrawal_policy.md").read_text(encoding="utf-8")
    assert "$25,000" in large and "50% of the current account balance" in large  # D-02
    vulnerable = (KNOWLEDGE / "vulnerable_customer_policy.md").read_text(encoding="utf-8")
    assert "aged 80 or over" in vulnerable  # D-07
    waiver = (KNOWLEDGE / "waiver_review_procedure.md").read_text(encoding="utf-8")
    assert "does not have a general hardship waiver" in waiver  # D-03, matches faq.md


# ---------- #24: the large-withdrawal policy contradicted FR-07 ----------
# Found by /code-review on PR #20 (spec axis). FR-07: a quote on a non-active account is refused
# (NOT_PERMITTED); it is not a request for a reviewer (NEEDS_HUMAN).
def test_issue_24_inactive_accounts_are_refused_not_reviewed() -> None:
    text = (KNOWLEDGE / "large_withdrawal_policy.md").read_text(encoding="utf-8")
    review_section = text.split("### Which withdrawals are reviewed by a person", 1)[1]
    review_section = review_section.split("###", 1)[0]
    assert "the account status" not in review_section.lower()
    assert "**active**" not in review_section
    assert "cannot be processed" in text and "not active" in text


def test_issue_25_document_folders_are_not_empty() -> None:
    # Issue #25 (found by /code-review on PR #20): the parametrized tests passed vacuously if a
    # folder was empty or moved. Six documents in knowledge/, three in the starter kit.
    assert len(DOCS) >= 6
    assert len(list(STARTER.glob("*.md"))) == 3
