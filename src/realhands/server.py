"""MCP server: lets Claude operate the REAL desktop like a human.

Exposes a single `computer` tool (action enum modeled on Anthropic's reference
computer_20250124 tool). The `screenshot` action returns the real screen as an
image; every other action drives the real OS mouse/keyboard and then returns a
fresh screenshot so Claude always sees the result.

Works in your own logged-in Chrome and any other app, because it moves the
physical cursor — it is NOT a separate automated browser.
"""
from __future__ import annotations

import sys
import time

from mcp.server.fastmcp import FastMCP, Image

from . import config
from . import screen
from . import safety
from . import input as actions  # mouse/keyboard execution (real pixels)


mcp = FastMCP("computer-use")

# Settle time after an action before the follow-up screenshot, so UI can update.
_SETTLE = 0.4


def _image(data: bytes) -> Image:
    fmt = "jpeg" if config.IMAGE_FORMAT == "jpeg" else "png"
    return Image(data=data, format=fmt)


def _shot(prefix: str, monitor: int | None = None) -> list:
    """Capture and return [status text, screenshot image] as tool content."""
    data, sw, sh, rw, rh = screen.capture(monitor)
    text = f"{prefix}\nScreenshot is {sw}x{sh}px — give all coordinates in this space."
    return [text, _image(data)]


def _need_xy(coordinate, action: str, monitor: int | None = None) -> tuple[int, int]:
    if not coordinate or len(coordinate) != 2:
        raise ValueError(f"action '{action}' requires coordinate=[x, y]")
    return screen.to_real(int(coordinate[0]), int(coordinate[1]), monitor)


@mcp.tool()
def computer(
    action: str,
    coordinate: list[int] | None = None,
    text: str | None = None,
    scroll_direction: str | None = None,
    scroll_amount: int | None = None,
    duration: float | None = None,
    monitor: int | None = None,
) -> list:
    """Control the real computer: see the screen and act with the real mouse/keyboard.

    ALWAYS start a task with action="screenshot" to see the screen. Coordinates are
    in the pixel space of the most recent screenshot (its size is reported each time);
    the server scales them to the real display automatically. After every non-screenshot
    action a fresh screenshot is returned so you can see the result before the next step.
    When the task is COMPLETE, call action="stop" to stand down (it auto-stands-down
    after a short idle period regardless).

    Args:
        action: One of —
          screenshot      : capture the screen (returns an image).
          cursor_position : report where the mouse is.
          mouse_move      : move the cursor to coordinate.
          left_click / right_click / middle_click / double_click / triple_click :
                            click at coordinate (or current position if omitted).
          left_click_drag : press at coordinate=[x2,y2] starting from `text`="x1,y1"
                            ... or pass start via coordinate and end via scroll fields
                            (prefer providing both via coordinate=end, text="x1,y1").
          left_mouse_down / left_mouse_up : press/release the left button at coordinate.
          scroll          : scroll at coordinate; needs scroll_direction
                            (up/down/left/right) and scroll_amount (wheel notches).
          type            : type the given `text` (handles Unicode/multiline).
          key             : press a key or chord, e.g. "Return", "ctrl+s", "alt+Tab".
          hold_key        : hold `text` keys for `duration` seconds.
          activate_window : bring an app to the FRONT by title substring in `text`
                            (e.g. "Chrome", "New tab", "Code") — prefer this over
                            clicking the taskbar when you need to switch apps.
          monitors        : list the detected monitors (for multi-screen setups).
          stop            : stand down — close the STOP overlay and release the
                            panic hotkey. CALL THIS as your final action when the
                            task is complete. (Also auto-stands-down after idle.)
          wait            : sleep for `duration` seconds, then screenshot.
        coordinate: [x, y] in the latest screenshot's pixel space.
        text: text to type, key name/chord, or "x1,y1" drag origin.
        scroll_direction: up | down | left | right (for scroll).
        scroll_amount: number of wheel notches (for scroll).
        duration: seconds (for hold_key / wait).
        monitor: which screen to view/act on — 1=primary (default), 2.. = other
                 monitors, 0 = ALL screens at once. Call action="monitors" first to
                 see the setup. Use the SAME monitor for a click as for the
                 screenshot you're clicking on.

    Returns:
        A list of content (status text + screenshot image).
    """
    act = (action or "").strip().lower()

    # Stand down when work is done — release the STOP overlay + panic hotkey.
    if act in ("stop", "done", "release"):
        safety.stop()
        return ["Stood down: STOP overlay closed and panic hotkey released. "
                "I'll re-arm automatically on the next action."]

    safety.start()  # lazily arm STOP overlay + panic hotkey (re-arms after a stop)
    safety.set_status(f"{act} {coordinate or ''} {text or ''}".strip())

    try:
        if act == "screenshot":
            return _shot("Screenshot taken.", monitor)

        if act == "cursor_position":
            x, y = actions.cursor_position()
            return [f"Cursor at real pixel ({x}, {y})."]

        if act == "monitors":
            mons = screen.list_monitors()
            lines = [f"  [{m['index']}] {m['role']}: {m['width']}x{m['height']} "
                     f"at ({m['left']},{m['top']})" for m in mons]
            return ["Detected monitors (pass `monitor=<index>`):\n" + "\n".join(lines)]

        if act == "mouse_move":
            x, y = _need_xy(coordinate, act, monitor)
            actions.move(x, y)

        elif act in ("left_click", "right_click", "middle_click",
                     "double_click", "triple_click"):
            button = {"left_click": "left", "right_click": "right",
                      "middle_click": "middle", "double_click": "left",
                      "triple_click": "left"}[act]
            clicks = {"double_click": 2, "triple_click": 3}.get(act, 1)
            if coordinate:
                x, y = _need_xy(coordinate, act, monitor)
                actions.click(x, y, button=button, clicks=clicks)
            else:
                cx, cy = actions.cursor_position()
                actions.click(cx, cy, button=button, clicks=clicks)

        elif act == "left_click_drag":
            x2, y2 = _need_xy(coordinate, act, monitor)
            if not text or "," not in text:
                raise ValueError("left_click_drag needs text='x1,y1' as the drag origin")
            ox, oy = (int(v) for v in text.split(",")[:2])
            x1, y1 = screen.to_real(ox, oy, monitor)
            actions.drag(x1, y1, x2, y2)

        elif act == "left_mouse_down":
            x, y = _need_xy(coordinate, act, monitor)
            actions.mouse_down(x, y)

        elif act == "left_mouse_up":
            x, y = _need_xy(coordinate, act, monitor)
            actions.mouse_up(x, y)

        elif act == "scroll":
            x, y = _need_xy(coordinate, act, monitor)
            actions.scroll(x, y, scroll_direction or "down", scroll_amount or 3)

        elif act == "type":
            if text is None:
                raise ValueError("action 'type' requires text")
            actions.type_text(text)

        elif act == "key":
            if not text:
                raise ValueError("action 'key' requires text (e.g. 'ctrl+s')")
            actions.key(text)

        elif act == "hold_key":
            if not text:
                raise ValueError("action 'hold_key' requires text")
            actions.hold_key(text, duration or 1.0)

        elif act == "activate_window":
            if not text:
                raise ValueError("action 'activate_window' requires text (a window title substring)")
            msg = actions.activate_window(text)
            time.sleep(_SETTLE)
            return _shot(msg, monitor)

        elif act == "wait":
            time.sleep(max(0.0, float(duration or 1.0)))

        elif act != "screenshot":
            raise ValueError(f"unknown action: {action!r}")

    except Exception as exc:  # includes pyautogui.FailSafeException
        name = type(exc).__name__
        if "FailSafe" in name:
            return ["ABORTED: mouse moved to the fail-safe corner. Automation halted."]
        raise

    # Non-screenshot action succeeded — show the result.
    time.sleep(_SETTLE)
    return _shot(f"Did: {act}.", monitor)


def main() -> None:
    screen.set_dpi_awareness()
    safety.configure()
    # safety.start() is deferred to the first `computer` tool call (see the tool body)
    # so idle sessions don't show the overlay or grab the panic hotkey.
    print(
        f"[computer-use-mcp] ready — monitor={config.MONITOR} "
        f"max_dim={config.MAX_DIM} panic={config.PANIC_HOTKEY} overlay={config.OVERLAY}",
        file=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
