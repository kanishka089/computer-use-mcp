"""Environment-driven configuration for the computer-use-mcp server."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent.resolve()       # src/
_ROOT = _HERE.parent                           # repo root
load_dotenv(_ROOT / ".env")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# --- Screen / coordinate grounding ---
# Claude bills images by 28x28 patches: tokens = ceil(w/28) * ceil(h/28). A
# dimension that isn't a multiple of 28 pays for a partial patch row/column that
# carries almost no pixels, so 1260x700 (45x25 patches = 1125 tokens) is strictly
# cheaper than 1280x720 (46x26 = 1196) for 1.5% fewer pixels. See PATCH_ALIGN.
MAX_DIM: int = _int("COMPUTER_USE_MAX_DIM", 1260)
MONITOR: int = _int("COMPUTER_USE_MONITOR", 1)
IMAGE_FORMAT: str = os.environ.get("COMPUTER_USE_IMAGE_FORMAT", "png").strip().lower()

# Round the sent image down to whole 28px patches so no tokens are spent on a
# sliver of a patch. Costs <28px per axis; saves ~6% of every screenshot.
PATCH_ALIGN: bool = _bool("COMPUTER_USE_PATCH_ALIGN", True)

# --- Token economy ---
# If fewer than this fraction of pixels materially changed since the last image
# we sent, return a one-line note instead of a fresh screenshot. An idle desktop
# never produces byte-identical frames (clock, caret, hover states), so this is a
# threshold rather than an equality check. 0 disables.
CHANGE_THRESHOLD: float = _float("COMPUTER_USE_CHANGE_THRESHOLD", 0.002)

# Never suppress more than this many screenshots in a row — a resync guards
# against the model flying blind if it lost the earlier image to compaction.
MAX_SKIPS: int = _int("COMPUTER_USE_MAX_SKIPS", 6)

# --- Pacing / safety ---
PAUSE: float = _float("COMPUTER_USE_PAUSE", 0.15)
PANIC_HOTKEY: str = os.environ.get("COMPUTER_USE_PANIC_HOTKEY", "ctrl+alt+q").strip()
OVERLAY: bool = _bool("COMPUTER_USE_OVERLAY", True)
MOVE_DURATION: float = _float("COMPUTER_USE_MOVE_DURATION", 0.4)

# Stand down (hide overlay + release panic hotkey) after this many seconds with no
# action. Default 0 = DISABLED: stand down only when the agent calls action="stop"
# at the end of a task. (An agent's thinking time between tool calls routinely
# exceeds any short idle window, so a non-zero value here will stand down mid-task.)
IDLE_STOP: float = _float("COMPUTER_USE_IDLE_STOP", 0.0)
