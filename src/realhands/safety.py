"""Kill switches + stand-down for fully-autonomous operation.

Three independent ways to stop the agent instantly:
  1. FAILSAFE corner  — slam the mouse into the top-left corner (pyautogui raises).
  2. Panic hotkey     — a global hotkey (default ctrl+alt+q) hard-kills the process.
  3. STOP overlay     — an always-on-top window with a big STOP button.

The active footprint (overlay window + global panic hotkey) is armed lazily on the
first action and STANDS DOWN when work is done — either explicitly via stop() or
automatically after IDLE_STOP seconds of inactivity. The lightweight stdio process
stays connected so the next task is instant, but nothing intrusive lingers while idle.
"""
from __future__ import annotations

import os
import threading
import time

import pyautogui

from . import config

_status = "idle"
_started = False
_last_activity = 0.0
_hotkey_handle = None
_overlay_close: threading.Event | None = None
_watchdog_started = False


def configure() -> None:
    """Apply global pyautogui safety/pacing settings + start the idle watchdog."""
    pyautogui.FAILSAFE = True          # mouse to (0,0) corner -> FailSafeException
    pyautogui.PAUSE = config.PAUSE     # delay after each action; keeps it interruptible
    _start_watchdog()


def _note_activity() -> None:
    global _last_activity
    _last_activity = time.monotonic()


def set_status(text: str) -> None:
    """Update the STOP overlay text and mark the agent as active."""
    global _status
    _status = text
    _note_activity()


def _panic() -> None:
    # Hardest possible stop: terminate the process now.
    os._exit(1)


# --- panic hotkey ---

def _start_hotkey() -> None:
    global _hotkey_handle
    try:
        import keyboard
        _hotkey_handle = keyboard.add_hotkey(config.PANIC_HOTKEY, _panic)
    except Exception:
        _hotkey_handle = None


def _stop_hotkey() -> None:
    global _hotkey_handle
    try:
        import keyboard
        if _hotkey_handle is not None:
            keyboard.remove_hotkey(_hotkey_handle)
    except Exception:
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
    _hotkey_handle = None


# --- STOP overlay ---

def _start_overlay() -> None:
    global _overlay_close
    try:
        import tkinter as tk
    except Exception:
        return

    _overlay_close = threading.Event()
    close_evt = _overlay_close

    def run() -> None:
        root = tk.Tk()
        root.title("computer-use")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        root.geometry("220x96-12+12")  # top-right corner
        try:
            root.attributes("-alpha", 0.92)
        except Exception:
            pass

        status_var = tk.StringVar(value=_status)
        tk.Label(root, textvariable=status_var, font=("Segoe UI", 9),
                 wraplength=200, justify="left").pack(fill="x", padx=8, pady=(8, 4))
        tk.Button(root, text="■  STOP AGENT", fg="white", bg="#c0392b",
                  activebackground="#e74c3c", activeforeground="white",
                  font=("Segoe UI", 11, "bold"), relief="flat",
                  command=_panic).pack(fill="x", padx=8, pady=(0, 8))

        def tick() -> None:
            if close_evt.is_set():
                try:
                    root.destroy()
                except Exception:
                    pass
                return
            status_var.set(_status)
            root.after(200, tick)

        tick()
        root.mainloop()

    threading.Thread(target=run, daemon=True).start()


def _stop_overlay() -> None:
    if _overlay_close is not None:
        _overlay_close.set()


# --- arm / stand down ---

def start() -> None:
    """Arm the overlay + panic hotkey (and mark active). Idempotent; re-arms after stop()."""
    global _started
    _note_activity()
    if _started:
        return
    _started = True
    _start_hotkey()
    if config.OVERLAY:
        _start_overlay()


def stop() -> None:
    """Stand down: close the STOP overlay and release the panic hotkey, go dormant.

    Re-arms automatically on the next action. Safe to call when already dormant.
    """
    global _started, _status
    if not _started:
        return
    _started = False
    _status = "idle"
    _stop_hotkey()
    _stop_overlay()


def _start_watchdog() -> None:
    """Background thread that stands down after IDLE_STOP seconds of inactivity."""
    global _watchdog_started
    if _watchdog_started or config.IDLE_STOP <= 0:
        return
    _watchdog_started = True

    def loop() -> None:
        while True:
            time.sleep(1.0)
            if _started and (time.monotonic() - _last_activity) > config.IDLE_STOP:
                stop()

    threading.Thread(target=loop, daemon=True).start()
