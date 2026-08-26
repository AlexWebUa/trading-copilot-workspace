"""
Pine Script generation — shared by the copilot's `generate_pine_script` tool
and the `scripts/debug_detectors.py` CLI.

  emitters.py — per-detector Pine bodies (moved verbatim from the debug script)
  runners.py  — how each detector is invoked to produce those bodies
  overlay.py  — merges selected layers into one toggle-able indicator
  store.py    — writes the .pine artifact to ~/.trading-copilot/pine/
"""

from copilot.pine.emitters import EMITTERS, EmitContext, emit
from copilot.pine.overlay import OVERLAY_LAYERS, build_overlay, layer_toggle
from copilot.pine.runners import RunDeps, run
from copilot.pine.store import list_recent_pine, pine_dir, save_pine

__all__ = [
    "EMITTERS",
    "EmitContext",
    "emit",
    "OVERLAY_LAYERS",
    "build_overlay",
    "layer_toggle",
    "RunDeps",
    "run",
    "list_recent_pine",
    "pine_dir",
    "save_pine",
]
