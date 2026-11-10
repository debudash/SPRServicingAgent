"""Runtime settings, read from the process environment only (no .env files here)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_AS_OF = "2024-12-01"
DEFAULT_VAR_DIR = "var"


@dataclass(frozen=True)
class Settings:
    as_of: str
    var_dir: Path
    # FR-26 kill switch. Only the word "true" (any case) turns execution on, so a typo fails
    # closed; an unset variable keeps the documented default, on (.env.example).
    execution_enabled: bool = True
    # GR-18: the HMAC key for approval tokens. Empty means no token can be issued or checked
    # (contracts.tokens refuses it). Kept out of repr so it never reaches a log.
    approval_secret: bytes = field(default=b"", repr=False)

    @property
    def desk_db(self) -> Path:
        return self.var_dir / "desk.db"

    @property
    def checkpoints_db(self) -> Path:
        return self.var_dir / "checkpoints.db"

    @property
    def chroma_dir(self) -> Path:
        return self.var_dir / "chroma"


def load_settings() -> Settings:
    """Read settings from the environment on every call, so tests can patch it."""
    return Settings(
        as_of=os.environ.get("DESK_AS_OF") or DEFAULT_AS_OF,
        var_dir=Path(os.environ.get("DESK_VAR_DIR") or DEFAULT_VAR_DIR),
        execution_enabled=(os.environ.get("EXECUTION_ENABLED") or "true").strip().lower() == "true",
        approval_secret=(os.environ.get("APPROVAL_SECRET") or "").encode(),
    )
