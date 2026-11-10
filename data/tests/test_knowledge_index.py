import hashlib
import re
from datetime import date
from pathlib import Path

from data.knowledge_index.index import ChromaKnowledgeSearch
from data.knowledge_index.loader import load_chunks

REPO = Path(__file__).resolve().parents[2]
DIM = 256


class HashingEmbedding:
    """Deterministic bag-of-words hashing embeddings; no model, no network."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def name() -> str:
        return "test-hashing"

    def get_config(self) -> dict[str, int]:
        return {"dim": DIM}

    @staticmethod
    def build_from_config(config: dict[str, int]) -> "HashingEmbedding":
        return HashingEmbedding()

    def is_legacy(self) -> bool:
        return False

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def __call__(self, input: list[str]) -> list[list[float]]:
        out = []
        for text in input:
            vec = [0.0] * DIM
            for w in re.findall(r"[a-z0-9.%]+", text.lower()):
                vec[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
            out.append(vec)
        return out


def _index(tmp_path: Path) -> ChromaKnowledgeSearch:
    return ChromaKnowledgeSearch(tmp_path / "chroma", HashingEmbedding())


def test_real_knowledge_queries(tmp_path: Path) -> None:
    idx = _index(tmp_path)
    idx.rebuild(load_chunks(REPO / "knowledge"))
    top = idx.search("surrender charge in year 5", date(2024, 12, 1), k=3)
    assert "fee_schedule" in {c.doc_id for c in top}
    rate = idx.search("interest rate", date(2024, 12, 1), k=3)
    assert any("4.25%" in c.text for c in rate)


def test_real_knowledge_answers_only_from_versions_in_force(tmp_path: Path) -> None:
    """At the as-of date every chunk returned is the version in force for its document, however
    many superseded versions knowledge/ keeps (GR-04, #123)."""
    chunks = load_chunks(REPO / "knowledge")
    as_of = date(2024, 12, 1)  # PRD D-04
    in_force: dict[str, int] = {}
    for c in chunks:
        if c.effective_date <= as_of:
            in_force[c.doc_id] = max(in_force.get(c.doc_id, 0), c.version)
    idx = _index(tmp_path)
    idx.rebuild(chunks)
    got = idx.search("surrender charge rate in contract year 5", as_of, k=len(chunks))
    assert got
    assert all(c.version == in_force[c.doc_id] for c in got)


def _doc(folder: Path, name: str, version: int, eff: str, body: str) -> None:
    (folder / name).write_text(
        f"---\ndoc_id: policy\nversion: {version}\neffective_date: {eff}\n---\n### Rule\n{body}\n"
    )


def test_as_of_picks_version_in_force(tmp_path: Path) -> None:
    folder = tmp_path / "knowledge"
    folder.mkdir()
    _doc(folder, "p1.md", 1, "2020-01-01", "alpha limit is ten")
    _doc(folder, "p2.md", 2, "2024-06-01", "alpha limit is twenty")
    _doc(folder, "p3.md", 3, "2030-01-01", "alpha limit is thirty")
    idx = _index(tmp_path)
    idx.rebuild(load_chunks(folder))
    for as_of, version in [
        (date(2023, 1, 1), 1),
        (date(2024, 6, 1), 2),
        (date(2025, 1, 1), 2),
        (date(2031, 1, 1), 3),
    ]:
        got = idx.search("alpha limit", as_of, k=10)
        assert [c.version for c in got] == [version]
    assert idx.search("alpha limit", date(2019, 1, 1)) == []
