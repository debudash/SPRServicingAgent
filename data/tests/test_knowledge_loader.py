from collections import Counter
from pathlib import Path

import pytest

from data.knowledge_index.loader import load_chunks

REPO = Path(__file__).resolve().parents[2]


def test_real_knowledge_counts() -> None:
    # Superseded versions stay in knowledge/ beside the current one (knowledge/README.md), so
    # count the latest version of each document (#123).
    chunks = load_chunks(REPO / "knowledge")
    latest = {c.doc_id: max(x.version for x in chunks if x.doc_id == c.doc_id) for c in chunks}
    counts = Counter(c.doc_id for c in chunks if c.version == latest[c.doc_id])
    assert counts["fee_schedule"] == 5
    assert counts["product_summary"] == 7
    assert counts["faq"] == 12
    assert all(c.text.strip() for c in chunks)
    assert "README" not in {Path(c.source_path).stem for c in chunks}
    faq = [c for c in chunks if c.doc_id == "faq"]
    assert len({(c.doc_id, c.version) for c in chunks if c.doc_id == "faq"}) == 1
    assert faq[0].section == "Is my money safe if SPR Financials goes out of business?"
    assert faq[0].source_path == "knowledge/faq.md"


def test_missing_front_matter_names_file(tmp_path: Path) -> None:
    folder = tmp_path / "knowledge"
    folder.mkdir()
    (folder / "bad.md").write_text("### A\ntext\n")
    with pytest.raises(ValueError, match="bad.md"):
        load_chunks(folder)
