"""Chroma-backed KnowledgeSearch: only versions in force at the as-of date (FR-01, FR-24)."""

from datetime import date
from pathlib import Path
from typing import Any, cast

import chromadb
from chromadb.api.types import EmbeddingFunction, Where

from contracts.ports import KnowledgeChunk

COLLECTION = "knowledge"


def _key(doc_id: str, version: int) -> str:
    return f"{doc_id}@{version}"


class ChromaKnowledgeSearch:
    """Implements `contracts.ports.KnowledgeSearch` over chunks from the loader."""

    def __init__(self, path: Path, embedding_function: Any) -> None:
        self._client = chromadb.PersistentClient(path=str(path))
        self._ef = cast(EmbeddingFunction[Any], embedding_function)
        self._collection = self._client.get_or_create_collection(
            COLLECTION,
            embedding_function=self._ef,
            configuration={"hnsw": {"space": "cosine"}},
        )

    def rebuild(self, chunks: list[KnowledgeChunk]) -> int:
        """Replace the whole index with `chunks`, storing every chunk's metadata."""
        self._client.delete_collection(COLLECTION)
        self._collection = self._client.create_collection(
            COLLECTION,
            embedding_function=self._ef,
            configuration={"hnsw": {"space": "cosine"}},
        )
        if not chunks:
            return 0
        self._collection.add(
            ids=[f"{_key(c.doc_id, c.version)}#{i}" for i, c in enumerate(chunks)],
            documents=[f"{c.section}\n{c.text}" for c in chunks],
            metadatas=[
                {
                    "doc_id": c.doc_id,
                    "version": c.version,
                    "effective_date": c.effective_date.isoformat(),
                    "section": c.section,
                    "text": c.text,
                    "source_path": c.source_path,
                    "doc_key": _key(c.doc_id, c.version),
                }
                for c in chunks
            ],
        )
        return len(chunks)

    def _in_force(self, as_of: date, doc_ids: frozenset[str] | None) -> list[str]:
        """`doc_id@version` keys: per doc_id the highest version effective on or before as_of,
        limited to `doc_ids` when given."""
        metas = self._collection.get(include=["metadatas"])["metadatas"] or []
        best: dict[str, int] = {}
        for m in metas:
            if doc_ids is not None and str(m["doc_id"]) not in doc_ids:
                continue
            if date.fromisoformat(str(m["effective_date"])) <= as_of:
                doc_id, version = str(m["doc_id"]), int(cast(int, m["version"]))
                best[doc_id] = max(best.get(doc_id, 0), version)
        return [_key(d, v) for d, v in best.items()]

    def search(self, query: str, as_of: date, k: int = 4) -> list[KnowledgeChunk]:
        return self.search_documents(query, as_of, k, doc_ids=None)

    def search_documents(
        self, query: str, as_of: date, k: int, doc_ids: frozenset[str] | None
    ) -> list[KnowledgeChunk]:
        """`search`, restricted to `doc_ids` (None: every document). The restriction is in the
        query's filter, so a document outside it can never be returned (FR-22)."""
        keys = self._in_force(as_of, doc_ids)
        if not keys or k < 1:
            return []
        res = self._collection.query(
            query_texts=[query],
            n_results=k,
            where=cast(Where, {"doc_key": {"$in": keys}}),
            include=["metadatas", "distances"],
        )
        metas = (res["metadatas"] or [[]])[0]
        dists = (res["distances"] or [[]])[0]
        return [
            KnowledgeChunk(
                doc_id=str(m["doc_id"]),
                version=int(cast(int, m["version"])),
                effective_date=date.fromisoformat(str(m["effective_date"])),
                section=str(m["section"]),
                text=str(m["text"]),
                source_path=str(m["source_path"]),
                score=1.0 - float(d),
            )
            for m, d in zip(metas, dists, strict=True)
        ]
