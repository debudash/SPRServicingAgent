"""Chroma RAG over the SPR knowledge base — product/fee/FAQ grounding.

Answers to product questions must come from these docs (or tool output), never
from model memory. Heavy imports are lazy so importing agent.tools stays cheap.
"""
import config

_embeddings = None
_store = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings  # lazy: heavy
        _embeddings = HuggingFaceEmbeddings(model_name=config.EMBED_MODEL)
    return _embeddings


def get_store():
    global _store
    if _store is None:
        from langchain_chroma import Chroma  # lazy: heavy
        _store = Chroma(collection_name=config.CHROMA_COLLECTION,
                        embedding_function=_get_embeddings(),
                        persist_directory=config.CHROMA_DIR)
    return _store


def search(query: str, k: int = 3):
    hits = get_store().similarity_search(query, k=k)
    return [{"source": h.metadata.get("source", "kb"), "text": h.page_content} for h in hits]
