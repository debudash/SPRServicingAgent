"""Build the Chroma index from the SPR knowledge base.

Run once (re-runnable):  python -m data.ingest
Loads knowledge_base/*.md, splits, embeds locally, persists to CHROMA_DIR.
"""
import glob
import os

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from data.retriever import _get_embeddings


def main():
    paths = sorted(glob.glob(os.path.join(config.KB_DIR, "*.md")))
    texts, metadatas = [], []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            texts.append(f.read())
        metadatas.append({"source": os.path.basename(p)})
    if not texts:
        print(f"No .md files in {config.KB_DIR}"); return

    docs = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100) \
        .create_documents(texts, metadatas=metadatas)
    print(f"{len(texts)} KB files -> {len(docs)} chunks")
    Chroma.from_documents(documents=docs, embedding=_get_embeddings(),
                          collection_name=config.CHROMA_COLLECTION,
                          persist_directory=config.CHROMA_DIR)
    print(f"Persisted to {config.CHROMA_DIR}. Done.")


if __name__ == "__main__":
    main()
