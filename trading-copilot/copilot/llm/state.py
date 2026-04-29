"""
Analysis state persistence.

After each analysis, saves all detector results to
  ~/.trading-copilot/reports/{SYMBOL}_{YYYYMMDD}.state.json

On the next analysis of the same symbol, loads the most recent state and
produces a diff summary injected into the system prompt as
  # Previous Analysis Context
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    return Path.home() / ".trading-copilot" / "reports"


def save_state(symbol: str, tool_results: dict[str, Any]) -> Path:
    """
    Persist tool_results to a state file.  Also pre-computes a diff context
    block by comparing against the previous saved state, so the NEXT analysis
    can inject it without re-running detectors.
    """
    prev_state = load_state(symbol)
    context_block = ""
    if prev_state:
        context_block = build_context_block(prev_state, tool_results)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = _state_dir() / f"{symbol.upper()}_{date_str}.state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": symbol.upper(),
        "date": date_str,
        "ts_saved": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": tool_results,
        "context_block": context_block,
    }
    path.write_text(json.dumps(payload, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_state(symbol: str) -> dict | None:
    """Return the most recent state snapshot for the symbol, or None."""
    d = _state_dir()
    if not d.exists():
        return None
    prefix = f"{symbol.upper()}_"
    candidates = sorted(
        [p for p in d.glob(f"{prefix}*.state.json")],
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        return None
    try:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception:
        return None


def build_context_block(prev_state: dict, curr_results: dict[str, Any]) -> str:
    """
    Compare curr_results against prev_state["results"] and return a
    markdown diff summary to inject into the system prompt.
    """
    prev = prev_state.get("results", {})
    prev_date = prev_state.get("date", "?")
    lines = [f"Previous analysis date: {prev_date}", ""]

    # FVG state changes
    fvg_changes: list[str] = []
    for key, curr in curr_results.items():
        if not isinstance(curr, dict):
            continue
        prev_r = prev.get(key, {})
        # Compare FVGs
        curr_fvgs = {_fvg_id(z): z.get("fill_state", "untouched") for z in curr.get("fvgs", [])}
        prev_fvgs = {_fvg_id(z): z.get("fill_state", "untouched") for z in prev_r.get("fvgs", [])}
        for fid, state in curr_fvgs.items():
            old_state = prev_fvgs.get(fid)
            if old_state and old_state != state:
                fvg_changes.append(f"  FVG {fid}: {old_state} → {state}")

    if fvg_changes:
        lines.append("FVG state changes:")
        lines += fvg_changes
        lines.append("")

    # Liquidity pool sweep changes
    sweep_changes: list[str] = []
    for key, curr in curr_results.items():
        if not isinstance(curr, dict):
            continue
        prev_r = prev.get(key, {})
        curr_swept = {p.get("price"): p.get("is_swept", False) for p in curr.get("buyside_liquidity", [])}
        prev_swept = {p.get("price"): p.get("is_swept", False) for p in prev_r.get("buyside_liquidity", [])}
        for price, is_swept in curr_swept.items():
            if price and prev_swept.get(price) is False and is_swept:
                sweep_changes.append(f"  BSL {price}: swept ✓")
        curr_ssl = {p.get("price"): p.get("is_swept", False) for p in curr.get("sellside_liquidity", [])}
        prev_ssl = {p.get("price"): p.get("is_swept", False) for p in prev_r.get("sellside_liquidity", [])}
        for price, is_swept in curr_ssl.items():
            if price and prev_ssl.get(price) is False and is_swept:
                sweep_changes.append(f"  SSL {price}: swept ✓")

    if sweep_changes:
        lines.append("Liquidity swept since last analysis:")
        lines += sweep_changes
        lines.append("")

    # VP POC shift
    poc_shifts: list[str] = []
    for key, curr in curr_results.items():
        if not isinstance(curr, dict):
            continue
        prev_r = prev.get(key, {})
        curr_poc = curr.get("poc")
        prev_poc = prev_r.get("poc")
        if curr_poc and prev_poc and abs(curr_poc - prev_poc) / prev_poc > 0.005:
            tf_label = key.replace("detect_volume_profile_", "")
            poc_shifts.append(f"  POC {tf_label}: {prev_poc} → {curr_poc}")

    if poc_shifts:
        lines.append("Volume Profile POC shifts (>0.5%):")
        lines += poc_shifts
        lines.append("")

    # BOS direction change
    for key, curr in curr_results.items():
        if not isinstance(curr, dict):
            continue
        prev_r = prev.get(key, {})
        curr_dir = curr.get("direction")
        prev_dir = prev_r.get("direction")
        if curr_dir and prev_dir and curr_dir != prev_dir:
            bos_type = curr.get("type", "BOS")
            lines.append(f"Structure shift: {bos_type} {prev_dir} → {curr_dir}")
            lines.append("")

    if len(lines) <= 2:
        return ""  # nothing meaningful to report

    return "\n".join(lines).strip()


def _fvg_id(z: dict) -> str:
    return f"{z.get('type', '?')}_{z.get('upper', 0)}_{z.get('lower', 0)}"
