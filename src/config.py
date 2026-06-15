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
MAX_DIM: int = _int("COMPUTER_USE_MAX_DIM", 1280)
MONITOR: int = _int("COMPUTER_USE_MONITOR", 1)
IMAGE_FORMAT: str = os.environ.get("COMPUTER_USE_IMAGE_FORMAT", "png").strip().lower()

# --- Pacing / safety ---
PAUSE: float = _float("COMPUTER_USE_PAUSE", 0.15)
PANIC_HOTKEY: str = os.environ.get("COMPUTER_USE_PANIC_HOTKEY", "ctrl+alt+q").strip()
OVERLAY: bool = _bool("COMPUTER_USE_OVERLAY", True)
MOVE_DURATION: float = _float("COMPUTER_USE_MOVE_DURATION", 0.4)

# Stand down (close overlay + release panic hotkey) after this many seconds with
# no action. 0 disables the idle watchdog. The agent can also call action="stop".
IDLE_STOP: float = _float("COMPUTER_USE_IDLE_STOP", 30.0)
