"""Composition root: builds the runner with the real `data` implementations.

The only module in `agents/` that imports from `data/`; everything else depends on `contracts/`.
"""

import os
import sqlite3
from pathlib import Path

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from agents.runner import GraphDeskRunner
from contracts.ports import DeskRunner
from data.knowledge_index.index import ChromaKnowledgeSearch
from data.settings import load_settings
from data.store.audit import SqliteAuditLog
from data.store.db import open_db


class MissingApiKeyError(RuntimeError):
    """ANTHROPIC_API_KEY is not set, so no model call can be made."""


def require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise MissingApiKeyError("ANTHROPIC_API_KEY is not set")


def _open_shared_db(path: Path) -> sqlite3.Connection:
    """Migrate the desk database, then reopen it for use from Streamlit's script threads."""
    open_db(path).close()
    return sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)


def build_runner() -> DeskRunner:
    require_api_key()
    settings = load_settings()
    settings.var_dir.mkdir(parents=True, exist_ok=True)
    search = ChromaKnowledgeSearch(settings.chroma_dir, DefaultEmbeddingFunction())  # ADR 0006
    audit = SqliteAuditLog(_open_shared_db(settings.desk_db))
    return GraphDeskRunner(search=search, audit=audit)
