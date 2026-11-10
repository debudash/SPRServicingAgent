"""Composition root: builds the runner with the real `data` implementations.

The only module in `agents/` that imports from `data/`; everything else depends on `contracts/`.
"""

import json
import os
import sqlite3
from pathlib import Path

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from agents.nodes.common import Stores
from agents.runner import GraphDeskRunner
from contracts.ports import DeskRunner
from data.identity import SqliteIdentityCheck
from data.knowledge_index.index import ChromaKnowledgeSearch
from data.settings import load_settings
from data.store.accounts import SqliteAccountStore
from data.store.audit import SqliteAuditLog
from data.store.cases import SqliteCaseStore
from data.store.db import open_db
from data.store.seed import STARTER_KIT, seed_starter_kit


class MissingApiKeyError(RuntimeError):
    """ANTHROPIC_API_KEY is not set, so no model call can be made."""


def require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise MissingApiKeyError("ANTHROPIC_API_KEY is not set")


def open_desk_db(path: Path) -> sqlite3.Connection:
    """Migrate the desk database, then reopen it for use from Streamlit's script threads."""
    open_db(path).close()
    return sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)


def customer_ids() -> list[str]:
    """The starter kit's customers, for the UI's "signed in as" picker (auth is upstream)."""
    accounts = json.loads(STARTER_KIT.read_text(encoding="utf-8"))["accounts"]
    return [str(a["customer_id"]) for a in accounts]


def build_runner() -> DeskRunner:
    require_api_key()
    settings = load_settings()
    settings.var_dir.mkdir(parents=True, exist_ok=True)
    search = ChromaKnowledgeSearch(settings.chroma_dir, DefaultEmbeddingFunction())  # ADR 0006
    conn = open_desk_db(settings.desk_db)
    return GraphDeskRunner(search=search, audit=SqliteAuditLog(conn), stores=build_stores(conn))


def build_stores(conn: sqlite3.Connection) -> Stores:
    """The B2 stores over a migrated desk database, seeded from the starter kit (idempotent)."""
    seed_starter_kit(conn)
    identity = SqliteIdentityCheck(conn)
    return Stores(
        accounts=SqliteAccountStore(conn, identity),
        identity=identity,
        cases=SqliteCaseStore(conn),
    )
