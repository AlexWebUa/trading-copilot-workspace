"""
Knowledge Base loader.

Reads Obsidian-compatible markdown notes from the knowledge_base/ directory.
Parses YAML frontmatter (title, tags, aliases, status).
Returns Note objects for use by selector.py and prompt injection.

KB location: looks for knowledge_base/ relative to the trading-copilot project root,
or falls back to the path in config.toml.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class Note:
    title: str
    path: Path
    tags: list[str]
    aliases: list[str]
    status: str  # "defined" | "stub" | "partial"
    body: str

    def as_context_block(self) -> str:
        """Format for injection into a system prompt."""
        header = f"### {self.title}"
        meta = f"_Tags: {', '.join(self.tags)}  |  Source: {self.path.name}_\n"
        return f"{header}\n{meta}\n{self.body.strip()}\n"


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TAG_LINE_RE = re.compile(r"tags:\s*\[([^\]]*)\]")
_ALIAS_LINE_RE = re.compile(r"aliases:\s*\[([^\]]*)\]")
_TITLE_LINE_RE = re.compile(r"title:\s*(.+)")
_STATUS_LINE_RE = re.compile(r"status:\s*(\w+)")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    fm_raw = m.group(1)
    body = text[m.end():]

    title_m = _TITLE_LINE_RE.search(fm_raw)
    tags_m = _TAG_LINE_RE.search(fm_raw)
    alias_m = _ALIAS_LINE_RE.search(fm_raw)
    status_m = _STATUS_LINE_RE.search(fm_raw)

    tags = [t.strip().strip('"') for t in tags_m.group(1).split(",")] if tags_m else []
    aliases = [a.strip().strip('"') for a in alias_m.group(1).split(",")] if alias_m else []

    fm = {
        "title": title_m.group(1).strip() if title_m else "",
        "tags": [t for t in tags if t],
        "aliases": [a for a in aliases if a],
        "status": status_m.group(1).strip() if status_m else "defined",
    }
    return fm, body


def _find_kb_root(project_root: Path) -> Path:
    """Try sibling knowledge_base/ first, then config override."""
    sibling = project_root.parent / "knowledge_base"
    if sibling.exists():
        return sibling

    config_path = project_root / "config.toml"
    if config_path.exists():
        with config_path.open("rb") as f:
            cfg = tomllib.load(f)
        kb_path = Path(cfg.get("kb", {}).get("path", "../knowledge_base"))
        if not kb_path.is_absolute():
            kb_path = (project_root / kb_path).resolve()
        if kb_path.exists():
            return kb_path

    raise FileNotFoundError(
        f"Knowledge base not found. Expected at {sibling} or configured in config.toml."
    )


class KBLoader:
    def __init__(self, kb_root: Path | None = None):
        project_root = Path(__file__).parent.parent.parent
        self._root = kb_root or _find_kb_root(project_root)
        self._notes: list[Note] | None = None

    @property
    def root(self) -> Path:
        return self._root

    def load_all(self, skip_stubs: bool = False) -> list[Note]:
        if self._notes is not None:
            return self._notes

        notes: list[Note] = []
        for md in self._root.rglob("*.md"):
            # Skip index/admin files
            if md.name.startswith("_"):
                continue
            text = md.read_text(encoding="utf-8", errors="replace")

            fm, body = _parse_frontmatter(text)
            if skip_stubs and fm.get("status") == "stub":
                continue

            title = fm.get("title") or md.stem.replace("_", " ")
            notes.append(Note(
                title=title,
                path=md,
                tags=fm.get("tags", []),
                aliases=fm.get("aliases", []),
                status=fm.get("status", "defined"),
                body=body,
            ))

        self._notes = notes
        return notes

    def get_by_path(self, relative_path: str) -> Note | None:
        """Load a specific note by path relative to KB root."""
        target = (self._root / relative_path).resolve()
        for note in self.load_all():
            if note.path.resolve() == target:
                return note
        # Direct load if not yet indexed
        p = self._root / relative_path
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            fm, body = _parse_frontmatter(text)
            return Note(
                title=fm.get("title") or p.stem,
                path=p,
                tags=fm.get("tags", []),
                aliases=fm.get("aliases", []),
                status=fm.get("status", "defined"),
                body=body,
            )
        return None

    def invalidate_cache(self) -> None:
        self._notes = None
