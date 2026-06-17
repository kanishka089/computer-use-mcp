"""Mouse + keyboard execution for computer-use-mcp.

All coordinates passed in here are REAL absolute screen pixels — the caller
(server.py) has already mapped model-space -> real via screen.to_real().

Keyboard names follow Claude's xdotool-style convention (Return, Page_Down,
ctrl+a, super, ...) which we translate to pyautogui's vocabulary.
"""
from __future__ import annotations

import time

import pyautogui
import pyperclip

from . import config

# xdotool / X11 keysym  ->  pyautogui key name
_KEY_MAP = {
    "return": "enter",
    "kp_enter": "enter",
    "enter": "enter",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "escape": "esc",
    "esc": "esc",
    "page_up": "pageup",
    "page_down": "pagedown",
    "prior": "pageup",
    "next": "pagedown",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "insert": "insert",
    "print": "printscreen",
    "menu": "apps",
    # modifiers
    "control": "ctrl",
    "control_l": "ctrl",
    "control_r": "ctrl",
    "ctrl": "ctrl",
    "alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "super": "win",
    "super_l": "win",
    "super_r": "win",
    "cmd": "win",
    "win": "win",
}


def _translate_token(tok: str) -> str:
    t = tok.strip()
    low = t.lower()
    if low in _KEY_MAP:
        return _KEY_MAP[low]
    if low.startswith("f") and low[1:].isdigit():  # F1..F24
        return low
    if len(t) == 1:  # letters / digits / punctuation
        return low
    return low  # best effort; pyautogui will raise if truly unknown


def _translate_combo(text: str) -> list[str]:
    """'ctrl+a' -> ['ctrl', 'a'];  'Return' -> ['enter']."""
    return [_translate_token(p) for p in text.split("+") if p.strip()]


# --- mouse ---

def move(x: int, y: int) -> None:
    pyautogui.moveTo(x, y, duration=config.MOVE_DURATION)


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    pyautogui.click(x, y, clicks=clicks, interval=0.08, button=button,
                    duration=config.MOVE_DURATION)


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left") -> None:
    pyautogui.moveTo(x1, y1, duration=config.MOVE_DURATION)
    pyautogui.dragTo(x2, y2, duration=max(config.MOVE_DURATION, 0.5), button=button)


def mouse_down(x: int, y: int, button: str = "left") -> None:
    pyautogui.moveTo(x, y, duration=config.MOVE_DURATION)
    pyautogui.mouseDown(button=button)


def mouse_up(x: int, y: int, button: str = "left") -> None:
    pyautogui.moveTo(x, y, duration=config.MOVE_DURATION)
    pyautogui.mouseUp(button=button)


def scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> None:
    pyautogui.moveTo(x, y, duration=config.MOVE_DURATION)
    direction = (direction or "down").lower()
    clicks = int(amount) * 100  # wheel notches -> a perceptible amount
    if direction == "up":
        pyautogui.scroll(clicks)
    elif direction == "down":
        pyautogui.scroll(-clicks)
    elif direction == "left":
        pyautogui.hscroll(-clicks)
    elif direction == "right":
        pyautogui.hscroll(clicks)


def cursor_position() -> tuple[int, int]:
    p = pyautogui.position()
    return int(p.x), int(p.y)


def activate_window(title: str) -> str:
    """Bring the first window whose title contains `title` to the foreground.

    Beats Windows' foreground-lock (which otherwise just flashes the taskbar
    instead of switching) using AttachThreadInput — we temporarily attach the
    current foreground window's input thread to ours so SetForegroundWindow is
    honored. A minimize/restore cycle is the guaranteed fallback. Far more
    reliable than clicking taskbar previews.
    """
    import pygetwindow as gw
    import win32api
    import win32con
    import win32gui
    import win32process

    matches = [w for w in gw.getAllWindows()
               if w.title and title.lower() in w.title.lower()]
    if not matches:
        titles = [w.title for w in gw.getAllWindows() if w.title][:12]
        return f"No window matching '{title}'. Open titles: {titles}"

    # Prefer a non-minimized match; fall back to the first.
    win = next((w for w in matches if not w.isMinimized), matches[0])
    hwnd = win._hWnd

    fg = win32gui.GetForegroundWindow()
    fg_thread = win32process.GetWindowThreadProcessId(fg)[0]
    cur_thread = win32api.GetCurrentThreadId()

    attached = False
    try:
        if fg_thread and fg_thread != cur_thread:
            win32process.AttachThreadInput(fg_thread, cur_thread, True)
            attached = True
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    finally:
        if attached:
            try:
                win32process.AttachThreadInput(fg_thread, cur_thread, False)
            except Exception:
                pass

    # Force the window to the TOP of the z-order without requiring focus rights.
    # A topmost->notopmost toggle reliably raises it above a focus-hungry host
    # (e.g. VS Code) so mouse clicks land on it even if keyboard focus is contested.
    try:
        flags = (win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    except Exception:
        pass

    # Guaranteed fallback: a minimize/restore cycle always activates the window.
    if win32gui.GetForegroundWindow() != hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    return f"Activated window: {win.title!r}"


# --- keyboard ---

def key(text: str) -> None:
    """Press a key or chord, e.g. 'Return', 'ctrl+s', 'alt+Tab'."""
    keys = _translate_combo(text)
    if not keys:
        return
    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)


def hold_key(text: str, duration: float) -> None:
    """Hold a key (or chord) down for `duration` seconds, then release."""
    keys = _translate_combo(text)
    for k in keys:
        pyautogui.keyDown(k)
    try:
        time.sleep(max(0.0, float(duration)))
    finally:
        for k in reversed(keys):
            pyautogui.keyUp(k)


def _is_simple_ascii(text: str) -> bool:
    return text.isascii() and "\n" not in text and "\t" not in text and len(text) <= 200


def type_text(text: str) -> None:
    """Type text. Fast path = pyautogui.write (ASCII); robust path = clipboard paste
    for long / Unicode / multiline content that write() mishandles."""
    if _is_simple_ascii(text):
        pyautogui.write(text, interval=0.012)
        return
    # Clipboard paste — preserve the user's existing clipboard.
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = None
    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)
    finally:
        if previous is not None:
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
