"""Composition root: builds the runner with the real `data` implementations.

The only module in `agents/` that imports from `data/`; everything else depends on `contracts/`.
"""

import json
import os
import sqlite3
from dataclasses import replace
from datetime import date
from functools import partial
from pathlib import Path

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from agents.nodes.common import MoneyPath, Stores
from agents.runner import GraphDeskRunner
from contracts.ports import LoginDeskRunner, PolicySource
from contracts.tokens import approval_token
from data.identity import SqliteIdentityCheck
from data.knowledge_index.index import ChromaKnowledgeSearch
from data.knowledge_index.policy import ChromaPolicySource
from data.settings import load_settings
from data.store.accounts import SqliteAccountStore
from data.store.audit import SqliteAuditLog
from data.store.cases import SqliteCaseStore
from data.store.db import open_db
from data.store.ledger import SqliteLedger
from data.store.proposals import SqliteApprovalStore, SqliteProposalStore
from data.store.quotes import SqliteQuoteService
from data.store.seed import STARTER_KIT, seed_demo_logins, seed_starter_kit


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
    """The starter kit's customers, for the login page's dropdown (ADR 0007)."""
    accounts = json.loads(STARTER_KIT.read_text(encoding="utf-8"))["accounts"]
    return [str(a["customer_id"]) for a in accounts]


def build_runner() -> LoginDeskRunner:
    require_api_key()
    settings = load_settings()
    settings.var_dir.mkdir(parents=True, exist_ok=True)
    search = ChromaKnowledgeSearch(settings.chroma_dir, DefaultEmbeddingFunction())  # ADR 0006
    conn = open_desk_db(settings.desk_db)
    # Issue #126: the runner's clock defaulted to date.today, so the live desk answered as of the
    # real date, not the as-of date (PRD D-04, DESK_AS_OF). Versions in force and date rules
    # follow the clock, so the wiring passes the setting.
    as_of = date.fromisoformat(settings.as_of)
    money = money_path(
        conn,
        ChromaPolicySource(search),
        secret=settings.approval_secret,
        execution_enabled=settings.execution_enabled,
    )
    return GraphDeskRunner(
        search=search,
        audit=SqliteAuditLog(conn),
        clock=lambda: as_of,
        stores=replace(build_stores(conn), money=money),
    )


def money_path(
    conn: sqlite3.Connection, policy: PolicySource, *, secret: bytes, execution_enabled: bool
) -> MoneyPath:
    """#89: Compliance's policy source, the approval store and the ledger over the desk database.
    The token issuer is bound to the secret here, so the agents lane never holds it."""
    return MoneyPath(
        policy=policy,
        approvals=SqliteApprovalStore(conn),
        ledger=SqliteLedger(
            conn, SqliteAuditLog(conn), secret=secret, execution_enabled=execution_enabled
        ),
        issue_token=partial(approval_token, secret=secret),
        execution_enabled=execution_enabled,
    )


def build_stores(conn: sqlite3.Connection) -> Stores:
    """The stores over a migrated desk database, seeded from the starter kit (idempotent). The
    demo passwords are seeded only when DESK_DEMO_LOGINS is on (ADR 0007, review on PR #109)."""
    seed_starter_kit(conn)
    if load_settings().demo_logins:
        seed_demo_logins(conn)
    identity = SqliteIdentityCheck(conn)
    accounts = SqliteAccountStore(conn, identity)
    return Stores(
        accounts=accounts,
        identity=identity,
        cases=SqliteCaseStore(conn),
        passwords=identity,
        quotes=SqliteQuoteService(accounts),  # #88
        proposals=SqliteProposalStore(conn),
    )
