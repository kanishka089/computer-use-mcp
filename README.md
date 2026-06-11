# computer-use-mcp ("realhands")

An MCP server that lets **Claude operate your real computer** the way a human does —
moving the **actual mouse**, clicking, typing, and reading the **actual screen**.

Unlike OpenAI Operator, browser-use, or Playwright agents (which spin up a separate,
isolated, logged-out Chrome), this drives the **physical OS cursor and keyboard**. So it
works in **your own Chrome with your own logged-in sessions** — and in every other app —
because it's just a human at the keyboard, as far as any website can tell.

**Status: LIVE and battle-tested.** Registered with Claude Code as the user-scope MCP
**`realhands`** (tool `mcp__realhands__computer`) and ✓Connected since 2026-06-02.
On 2026-06-09 it drove the user's real, logged-in Chrome through a **complete Google
Play Console deployment** (app upload, release notes, submission) end-to-end.

> The server is registered as `realhands` rather than `computer-use` because the name
> "computer-use" is reserved in Claude Code.

## How it works

Claude (Desktop or Code) is the agent loop. You type a task; Claude calls the single
`computer` tool in a see → think → act cycle:

> **See** — `screenshot` returns the real screen (downscaled to ~1280px for grounding accuracy)
> → **Think** — Claude picks the next action + pixel coordinates
> → **Act** — the server moves the real mouse / types on the real keyboard
> → a fresh screenshot comes back automatically after every action, and it repeats.

Two Windows-specific details make clicks land accurately (`src/screen.py`):

- **DPI awareness** — `SetProcessDpiAwareness(2)` is set at import time so screenshot
  pixels == pyautogui cursor coordinates even under display scaling (125% / 150% / …).
- **Stateless coordinate scaling** — screenshots are downscaled (LANCZOS) to at most
  `COMPUTER_USE_MAX_DIM` on the longest side before sending; incoming click coordinates
  are scaled back up to real pixels. The scale factor is a pure function of monitor
  geometry + `MAX_DIM`, so mapping never depends on which screenshot ran last.
  Coordinates are clamped inside the target monitor so a stray click can't fly off-screen.

**Multi-monitor:** every call takes an optional `monitor` index (1 = primary, 2.. =
others, 0 = the whole virtual desktop). `action="monitors"` enumerates the setup.
Origins may be negative for screens left/above the primary — `to_real()` handles the
offset. Use the **same** monitor for a click as for the screenshot you're clicking on.

## Architecture

```
src/
  server.py   FastMCP server "computer-use"; the single `computer` tool (action enum
              modeled on Anthropic's reference computer_20250124 tool); returns
              status text + a fresh screenshot after every action
  screen.py   DPI awareness, mss capture, downscale, model-space -> real-pixel mapping
  input.py    pyautogui mouse/keyboard execution; xdotool-style key-name translation
              (Return, Page_Down, ctrl+a, super, ...); clipboard-paste fast path for
              long/Unicode/multiline typing (preserves your existing clipboard);
              activate_window via win32 AttachThreadInput
  safety.py   kill switches + lazy arm / stand-down lifecycle
  config.py   .env-driven configuration (all defaults are sensible; .env is optional)
install.py    one-shot installer: venv, deps, .env, Claude Desktop registration
```

Stack: Python 3.10/3.11 · `mcp` (FastMCP, stdio) · `pyautogui` · `mss` · `pillow` ·
`pynput` · `keyboard` · `pyperclip` · `python-dotenv` — plus `pygetwindow` and `pywin32`
for `activate_window` (installed in the venv; not yet listed in `pyproject.toml`).

## The `computer` tool

A single tool with an `action` parameter:

| Action | What it does |
|---|---|
| `screenshot` | Capture the screen (always start a task with this) |
| `cursor_position` | Report the real mouse position |
| `monitors` | List detected monitors (for multi-screen setups) |
| `mouse_move` | Glide the cursor to `coordinate` |
| `left_click` / `right_click` / `middle_click` / `double_click` / `triple_click` | Click at `coordinate` (or current position) |
| `left_click_drag` | Drag from `text="x1,y1"` to `coordinate=[x2,y2]` |
| `left_mouse_down` / `left_mouse_up` | Press / release the left button |
| `scroll` | Scroll at `coordinate` (`scroll_direction` + `scroll_amount` notches) |
| `type` | Type `text` (clipboard-paste path for long/Unicode/multiline) |
| `key` | Press a key or chord — `"Return"`, `"ctrl+s"`, `"alt+Tab"` |
| `hold_key` | Hold keys for `duration` seconds |
| `activate_window` | Bring an app to the front by title substring (beats Windows' foreground-lock; far more reliable than clicking the taskbar) |
| `wait` | Sleep `duration` seconds, then screenshot |
| `stop` | Stand down: close the STOP overlay + release the panic hotkey (call as the final action) |

Coordinates are in the pixel space of the most recent screenshot; its size is reported
with every capture. After every non-screenshot action the tool waits ~0.4s for the UI
to settle and returns a fresh screenshot.

## Safety — it controls your REAL machine

This is **fully autonomous**: it does not ask before each action. Three independent
kill switches (`src/safety.py`):

1. **Fail-safe corner** — slam the mouse into the **top-left corner** → pyautogui raises
   `FailSafeException` and the action aborts instantly.
2. **Panic hotkey** — **Ctrl+Alt+Q** (configurable) → hard-kills the server process
   (`os._exit(1)`).
3. **STOP overlay** — an always-on-top window (top-right) showing the current action,
   with a big red **■ STOP AGENT** button that also hard-kills the process.

**Lazy arm / stand-down:** the overlay and the global panic hotkey are armed lazily on
the **first action** of a task, not at server startup — idle sessions show nothing and
grab no hotkeys. They stand down again when the agent calls `action="stop"`, or
automatically after `COMPUTER_USE_IDLE_STOP` seconds (default 30) of inactivity. The
lightweight stdio process stays connected so the next task is instant. Everything
re-arms automatically on the next action.

Pacing also helps you stay in control: every action is followed by a configurable pause
(`COMPUTER_USE_PAUSE`) and the cursor glides rather than teleports
(`COMPUTER_USE_MOVE_DURATION`), so you can watch and interrupt.

**Don't leave it unsupervised on anything that can spend money, send messages, or
delete data.**

## Install

Requires **Python 3.10 or 3.11** (3.13+ untested; avoid the 3.14 beta).

```powershell
cd d:\Company\AIOBDCODE\computer-use-mcp
py -3.10 install.py
```

This creates `.venv/`, installs the package + deps (editable), copies `.env.example` to
`.env` if missing, and registers the server in Claude Desktop's config (backing up any
existing config). **Restart Claude Desktop**, then look for the `computer-use` tool.

### Claude Code (how this machine runs it)

Registered as a **user-scope** stdio server named `realhands`:

```powershell
claude mcp add realhands --scope user -- `
  "d:/Company/AIOBDCODE/computer-use-mcp/.venv/Scripts/python.exe" `
  "d:/Company/AIOBDCODE/computer-use-mcp/src/server.py"
```

The tool then appears as `mcp__realhands__computer` in every project.

## Use

Just ask. For example:

> *Take a screenshot, open Chrome, go to YouTube, and search for "lofi".*

Watch your real cursor move and your logged-in Chrome respond. Real-world proof: it has
autonomously completed a full Google Play Console release flow in the user's own
signed-in Chrome session.

## Configuration (`.env`, optional — defaults are fine)

| Var | Default | Meaning |
|-----|---------|---------|
| `COMPUTER_USE_MAX_DIM` | `1280` | Longest screenshot side sent to Claude (sweet spot for accuracy + token cost) |
| `COMPUTER_USE_MONITOR` | `1` | Default monitor (1 = primary, 2.. = others, 0 = all screens); overridable per call |
| `COMPUTER_USE_IMAGE_FORMAT` | `png` | `png` (crisp text) or `jpeg` (cheaper tokens) |
| `COMPUTER_USE_PAUSE` | `0.15` | Delay after each pyautogui action (interruptibility) |
| `COMPUTER_USE_PANIC_HOTKEY` | `ctrl+alt+q` | Global hard-stop hotkey |
| `COMPUTER_USE_OVERLAY` | `1` | Show the STOP overlay window |
| `COMPUTER_USE_MOVE_DURATION` | `0.4` | Cursor glide time (human-like movement) |
| `COMPUTER_USE_IDLE_STOP` | `30` | Auto stand-down after this many idle seconds (0 = never) |

## Known gotchas

- **MCP connection drops when the agent idles between turns.** The stdio connection to
  `realhands` can silently die while Claude is thinking/waiting between turns. Fix: issue
  a `screenshot` action — it silently reconnects. Importantly, an action that "failed"
  with *Connection closed* **often still executed** on the real machine — take a
  screenshot and check the actual screen state before retrying, or you may double-click /
  double-submit.
- **Click coordinates must match the screenshot's monitor.** If you screenshot
  `monitor=2` and then click without passing `monitor=2`, the click lands on the primary.
- **`activate_window` beats the taskbar.** Windows' foreground-lock makes taskbar clicks
  unreliable (the icon just flashes). `activate_window` uses `AttachThreadInput` +
  z-order toggling + a minimize/restore fallback, so prefer it for app switching.
- **Don't run with Python 3.13/3.14.** Tested on 3.10/3.11 only; the installer warns.
- **`pygetwindow` / `pywin32` are venv-only.** They're required by `activate_window` but
  not yet declared in `pyproject.toml` — a fresh `pip install -e .` elsewhere would need
  them added manually.
- **Typing long/Unicode text uses the clipboard.** Your clipboard is saved and restored,
  but anything watching the clipboard will see the pasted text momentarily.

## Self-test

```powershell
.\.venv\Scripts\python src\screen.py
```

Captures the screen, prints real vs. sent dimensions and the scale factor, writes
`test_capture.png`, and runs a coordinate round-trip check (center + both corners).
