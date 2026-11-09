"""Rebuild the knowledge index: `python -m data.knowledge_index.ingest` (`make ingest`)."""

from pathlib import Path

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from data.knowledge_index.index import ChromaKnowledgeSearch
from data.knowledge_index.loader import load_chunks
from data.settings import load_settings

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"


def main() -> None:
    chroma_dir = load_settings().chroma_dir
    chroma_dir.mkdir(parents=True, exist_ok=True)
    index = ChromaKnowledgeSearch(chroma_dir, DefaultEmbeddingFunction())  # ADR 0006
    count = index.rebuild(load_chunks(KNOWLEDGE_DIR))
    print(f"indexed {count} chunks into {chroma_dir}")


if __name__ == "__main__":
    main()
