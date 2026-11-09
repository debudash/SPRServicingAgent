"""Split knowledge documents into citable chunks (ARCHITECTURE.md section 2.3)."""

import re
from pathlib import Path
from typing import Any

import yaml

from contracts.ports import KnowledgeChunk

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_HEADING = re.compile(r"^###[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_QUESTION = re.compile(r"^\*\*Q:[ \t]*(.+?)\*\*[ \t]*$", re.MULTILINE)
_REQUIRED = ("doc_id", "version", "effective_date")


def _split_front_matter(path: Path, raw: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER.match(raw)
    if match is None:
        raise ValueError(f"{path}: missing YAML front matter")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML front matter: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: front matter is not a mapping")
    missing = [key for key in _REQUIRED if key not in meta]
    if missing:
        raise ValueError(f"{path}: front matter missing {', '.join(missing)}")
    return meta, raw[match.end() :]


def _sections(body: str) -> list[tuple[str, str]]:
    """(section, text) pairs: by `###` heading, else by FAQ question."""
    matches = list(_HEADING.finditer(body)) or list(_QUESTION.finditer(body))
    pairs: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[m.end() : end].strip()
        # Trailing horizontal rules separate blocks; they are not content.
        text = re.sub(r"(?:\n\s*---\s*)+\Z", "", text).strip()
        if text:
            pairs.append((m.group(1).strip(), text))
    return pairs


def load_chunks(folder: Path) -> list[KnowledgeChunk]:
    """Chunk every document in `folder`, skipping README.md.

    `source_path` is relative to the folder's parent (the repo root).
    """
    root = folder.parent
    chunks: list[KnowledgeChunk] = []
    for path in sorted(folder.glob("*.md")):
        if path.name == "README.md":
            continue
        meta, body = _split_front_matter(path, path.read_text(encoding="utf-8"))
        source_path = path.relative_to(root).as_posix()
        for section, text in _sections(body):
            chunks.append(
                KnowledgeChunk(
                    doc_id=str(meta["doc_id"]),
                    version=meta["version"],
                    effective_date=meta["effective_date"],
                    section=section,
                    text=text,
                    source_path=source_path,
                )
            )
    return chunks
