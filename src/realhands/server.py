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


def _shot(prefix: str, monitor: int | None = None, force: bool = False) -> list:
    """Capture and return [status text, screenshot image] as tool content.

    Skips the image entirely when the screen is effectively unchanged since the
    last one we sent — a repeat screenshot is the single most expensive thing
    this server can do, because it is re-sent as history on every later turn.
    """
    data, sw, sh, _ = screen.capture_smart(monitor, force=force)
    if data is None:
        return [f"{prefix}\nScreen unchanged — the last screenshot is still accurate."]
    text = f"{prefix}\nScreenshot is {sw}x{sh}px — give all coordinates in this space."
    return [text, _image(data)]


def _need_xy(coordinate, action: str, monitor: int | None = None) -> tuple[int, int]:
    if not coordinate or len(coordinate) != 2:
        raise ValueError(f"action '{action}' requires coordinate=[x, y]")
    return screen.to_real(int(coordinate[0]), int(coordinate[1]), monitor)


# Answer in text and never need a screenshot to be understood.
_TEXT_ONLY = {"cursor_position", "monitors"}


def _run_one(
    act: str,
    coordinate: list[int] | None = None,
    text: str | None = None,
    scroll_direction: str | None = None,
    scroll_amount: int | None = None,
    duration: float | None = None,
    monitor: int | None = None,
) -> str:
    """Drive the real mouse/keyboard for ONE action and return a status line.

    Never captures the screen — the caller decides when an image is worth its
    tokens, which is what lets a batch of steps share a single screenshot.
    """
    if act == "screenshot":
        return "Screenshot taken."

    if act == "cursor_position":
        x, y = actions.cursor_position()
        return f"Cursor at real pixel ({x}, {y})."

    if act == "monitors":
        mons = screen.list_monitors()
        lines = [f"  [{m['index']}] {m['role']}: {m['width']}x{m['height']} "
                 f"at ({m['left']},{m['top']})" for m in mons]
        return "Detected monitors (pass `monitor=<index>`):\n" + "\n".join(lines)

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
        return actions.activate_window(text)

    elif act == "wait":
        time.sleep(max(0.0, float(duration or 1.0)))

    else:
        raise ValueError(f"unknown action: {act!r}")

    return f"Did: {act}."


@mcp.tool()
def computer(
    action: str | None = None,
    coordinate: list[int] | None = None,
    text: str | None = None,
    scroll_direction: str | None = None,
    scroll_amount: int | None = None,
    duration: float | None = None,
    monitor: int | None = None,
    steps: list[dict] | None = None,
    screenshot: bool = True,
) -> list:
    """Control the real computer: see the screen and act with the real mouse/keyboard.

    Start a task with action="screenshot". Give coordinates in the pixel space of
    the latest screenshot (its size is reported each time); they are scaled to the
    real display for you. A fresh screenshot comes back after each call, so you can
    see the result before deciding the next step. When the task is COMPLETE call
    action="stop" to stand down.

    BATCH WHENEVER YOU CAN. Pass `steps` — a list of action dicts run in order —
    instead of one call per action, and you pay for ONE screenshot instead of one
    per step. Batch every run of actions whose outcome you can already predict
    (filling a form, a click then type then Enter, a menu path). Split into
    separate calls only where you genuinely need to see the screen before choosing
    what to do next. Example:
      steps=[{"action":"left_click","coordinate":[420,300]},
             {"action":"type","text":"hello@example.com"},
             {"action":"key","text":"Tab"},
             {"action":"type","text":"secret"},
             {"action":"key","text":"Return"}]
    Set screenshot=false to skip the trailing image too, when you don't need to
    look at the result at all.

    Args:
        action: screenshot | cursor_position | mouse_move | left_click | right_click |
          middle_click | double_click | triple_click | left_click_drag (end via
          coordinate, origin via text="x1,y1") | left_mouse_down | left_mouse_up |
          scroll | type | key | hold_key | activate_window (bring an app to the front
          by title substring in `text` — prefer this over clicking the taskbar) |
          monitors | wait | stop.
        coordinate: [x, y] in the latest screenshot's pixel space.
        text: text to type, key name/chord ("Return", "ctrl+s"), window title, or
          "x1,y1" drag origin.
        scroll_direction: up | down | left | right.
        scroll_amount: wheel notches.
        duration: seconds (hold_key / wait).
        monitor: 1=primary (default), 2.. = others, 0 = all screens. Use the SAME
          monitor for a click as for the screenshot you are clicking on.
        steps: list of {action, coordinate, text, ...} dicts to run in order,
          sharing one screenshot at the end. Strongly preferred over many calls.
        screenshot: set false to suppress the trailing screenshot entirely.

    Returns:
        Status text, plus a screenshot image unless the screen is unchanged or
        screenshot=false.
    """
    act = (action or "").strip().lower()

    # Stand down when work is done — release the STOP overlay + panic hotkey.
    if not steps and act in ("stop", "done", "release"):
        safety.stop()
        return ["Stood down: STOP overlay closed and panic hotkey released. "
                "I'll re-arm automatically on the next action."]

    safety.start()  # lazily arm STOP overlay + panic hotkey (re-arms after a stop)

    # Normalize single-action and batch calls into one list of steps.
    if steps:
        plan = [dict(s) for s in steps]
    elif act:
        plan = [{"action": act, "coordinate": coordinate, "text": text,
                 "scroll_direction": scroll_direction, "scroll_amount": scroll_amount,
                 "duration": duration}]
    else:
        raise ValueError("pass either action=... or steps=[...]")

    done: list[str] = []
    failed = False
    for i, step in enumerate(plan, 1):
        sub = (step.get("action") or "").strip().lower()
        if sub in ("stop", "done", "release"):
            safety.stop()
            done.append("Stood down.")
            break
        safety.set_status(f"{sub} {step.get('coordinate') or ''} {step.get('text') or ''}".strip())
        try:
            done.append(_run_one(
                sub,
                coordinate=step.get("coordinate"),
                text=step.get("text"),
                scroll_direction=step.get("scroll_direction"),
                scroll_amount=step.get("scroll_amount"),
                duration=step.get("duration"),
                monitor=step.get("monitor", monitor),
            ))
        except Exception as exc:  # includes pyautogui.FailSafeException
            if "FailSafe" in type(exc).__name__:
                return ["ABORTED: mouse moved to the fail-safe corner. Automation halted."]
            # Report where the run stopped, then still show the screen so the
            # model can see the state it actually left behind.
            done.append(f"STEP {i} ({sub}) FAILED: {type(exc).__name__}: {exc}")
            failed = True
            break

    only_text = len(plan) == 1 and plan[0].get("action", "").lower() in _TEXT_ONLY
    summary = done[-1] if len(done) == 1 else "\n".join(
        f"{i}. {m}" for i, m in enumerate(done, 1))

    if only_text or (not screenshot and not failed):
        return [summary]

    time.sleep(_SETTLE)
    # Force a real image after a failure — that is exactly when a stale frame is
    # most likely and most costly to act on.
    return _shot(summary, monitor, force=failed)


def main() -> None:
    screen.set_dpi_awareness()
    safety.configure()
    # safety.start() is deferred to the first `computer` tool call (see the tool body)
    # so idle sessions don't show the overlay or grab the panic hotkey.
    _, sw, sh, rw, rh = screen.capture()
    print(
        f"[computer-use-mcp] ready — monitor={config.MONITOR} {rw}x{rh} "
        f"-> sends {sw}x{sh} ({screen.visual_tokens(sw, sh)} visual tokens/shot) "
        f"panic={config.PANIC_HOTKEY} overlay={config.OVERLAY}",
        file=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
