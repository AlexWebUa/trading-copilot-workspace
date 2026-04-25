"""
KB selector: picks which notes to inject into the system prompt.

Two-tier strategy (per plan):
1. Always-injected core notes (global rules, MOC, multi-TF, entry models, glossary).
2. Query-triggered notes: keyword match against tags + aliases + title.

Match scoring:
  - exact alias/tag hit = 3 pts
  - title substring = 2 pts
  - body keyword = 1 pt (only first 500 chars of body)

Returns ordered list of Notes, deduplicated, core notes first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from copilot.kb.loader import KBLoader, Note

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_DEFAULT_CORE_PATHS = [
    "00_Index/_Global_Rules.md",
    "00_Index/_MOC.md",
    "01_Concepts/Multi_TF_Analysis.md",
    "08_Entry_Models/Entry_Models.md",
    "99_Glossary/Glossary.md",
]

# Keyword → notes to inject (relative paths from KB root)
_KEYWORD_MAP: dict[str, list[str]] = {
    "silver bullet": ["08_Entry_Models/ICT_Silver_Bullet.md"],
    "1h3m": ["09_Setups/1h3m_by_Bellissimo.md"],
    "bellissimo": ["09_Setups/1h3m_by_Bellissimo.md"],
    "winstonfx": ["09_Setups/1h3m_by_WinstonFX.md", "09_Setups/Dynamic_Trading_System_WinstonFX.md"],
    "tgif": ["09_Setups/TGIF_Setup.md"],
    "nyse": ["09_Setups/NYSE_Open_Setups.md"],
    "stb": ["09_Setups/STB_BTS.md"],
    "bts": ["09_Setups/STB_BTS.md"],
    "judas": ["08_Entry_Models/ICT_Judas_Swing.md"],
    "vwap": ["04_Market_Profile/VWAP.md"],
    "wyckoff": ["01_Concepts/Wyckoff_Method.md"],
    "fvg": ["03_Tools/FVG.md"],
    "order block": ["03_Tools/Order_Block.md"],
    "ob": ["03_Tools/Order_Block.md"],
    "poi": ["07_POI"],  # directory: inject all POI notes
    "session": ["05_Sessions_Timings"],
    "isqra": ["09_Setups/Isqra_Strategy.md"],
}


class KBSelector:
    def __init__(self, loader: KBLoader | None = None, core_paths: list[str] | None = None):
        self._loader = loader or KBLoader()
        self._core_paths = core_paths or _load_core_paths_from_config() or _DEFAULT_CORE_PATHS

    def core_notes(self) -> list[Note]:
        """Always-injected notes."""
        notes = []
        for rel in self._core_paths:
            note = self._loader.get_by_path(rel)
            if note:
                notes.append(note)
        return notes

    def query_notes(self, query: str) -> list[Note]:
        """Return additional notes triggered by the user's query."""
        query_lower = query.lower()
        triggered_paths: set[str] = set()

        # Keyword map first (fast path)
        for keyword, paths in _KEYWORD_MAP.items():
            if keyword in query_lower:
                for p in paths:
                    triggered_paths.add(p)

        # Scoring fallback across all notes
        all_notes = self._loader.load_all()
        scored: list[tuple[int, Note]] = []
        tokens = re.findall(r"\w+", query_lower)

        for note in all_notes:
            score = 0
            title_lower = note.title.lower()
            for token in tokens:
                if any(token in a.lower() for a in note.aliases):
                    score += 3
                if any(token in t.lower() for t in note.tags):
                    score += 3
                if token in title_lower:
                    score += 2
                if token in note.body[:500].lower():
                    score += 1
            if score >= 3:
                scored.append((score, note))

        scored.sort(key=lambda x: -x[0])
        extra = [n for _, n in scored[:5]]

        # Merge path-triggered + scored
        result: list[Note] = []
        seen: set[Path] = set()

        for path_str in triggered_paths:
            note = self._loader.get_by_path(path_str)
            if note and note.path not in seen:
                result.append(note)
                seen.add(note.path)

        for note in extra:
            if note.path not in seen:
                result.append(note)
                seen.add(note.path)

        return result

    def select_for_query(self, query: str) -> tuple[list[Note], list[Note]]:
        """Return (core_notes, query_notes) for prompt building."""
        return self.core_notes(), self.query_notes(query)


def _load_core_paths_from_config() -> list[str] | None:
    config_file = Path(__file__).parent.parent.parent / "config.toml"
    if not config_file.exists():
        return None
    try:
        with config_file.open("rb") as f:
            cfg = tomllib.load(f)
        return cfg.get("kb", {}).get("always_inject")
    except Exception:
        return None
