"""Runtime settings, read from the process environment only (no .env files here)."""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AS_OF = "2024-12-01"
DEFAULT_VAR_DIR = "var"


@dataclass(frozen=True)
class Settings:
    as_of: str
    var_dir: Path

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
    )
