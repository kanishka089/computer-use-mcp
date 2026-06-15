"""Screen capture + coordinate scaling for computer-use-mcp.

Two jobs, both critical for accurate clicking on Windows:

1. DPI awareness — make the screenshot pixel grid match pyautogui's cursor
   coordinate space, so display scaling (125% / 150% / ...) doesn't offset clicks.
2. Coordinate scaling — Claude grounds best on ~1280px screenshots, so we
   downscale before sending and scale incoming click coordinates back up to
   real screen pixels (mirrors scale_coordinates() in Anthropic's reference impl).

Scaling here is STATELESS: the scale factor is a pure function of the monitor
geometry and MAX_DIM, so mapping a coordinate never depends on which screenshot
ran last.
"""
from __future__ import annotations

import io
import sys

import config


def set_dpi_awareness() -> None:
    """Tell Windows we handle DPI ourselves, so pixels == cursor coordinates.

    Must run before the first screenshot/cursor call. Safe to call more than once.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Windows 8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # legacy fallback
        except Exception:
            pass


# Set it at import — this module is imported before any capture/click happens.
set_dpi_awareness()

import mss  # noqa: E402  (import after DPI awareness on purpose)
from PIL import Image  # noqa: E402


def _monitor_geometry(monitor: int | None = None) -> tuple[int, int, int, int]:
    """Return (left, top, width, height) of a monitor in physical px.

    monitor index: 0 = the whole virtual desktop (ALL screens stitched together),
    1 = primary, 2.. = additional monitors. None falls back to config.MONITOR.
    Origins may be negative for screens left/above the primary — that's fine,
    mss grabs and to_real() handles the offset.
    """
    idx = config.MONITOR if monitor is None else int(monitor)
    with mss.MSS() as sct:
        mons = sct.monitors  # [0]=virtual all, [1]=primary, [2..]=others
        if not (0 <= idx < len(mons)):
            idx = 1 if len(mons) > 1 else 0
        m = mons[idx]
        return m["left"], m["top"], m["width"], m["height"]


def list_monitors() -> list[dict]:
    """Enumerate the detected monitors (auto-detects multi-screen setups)."""
    with mss.MSS() as sct:
        mons = sct.monitors
    out = []
    for i, m in enumerate(mons):
        role = ("all-screens (virtual desktop)" if i == 0
                else "primary" if i == 1 else f"monitor {i}")
        out.append({"index": i, "role": role, "width": m["width"],
                    "height": m["height"], "left": m["left"], "top": m["top"]})
    return out


def _scale_for(width: int, height: int) -> float:
    """Factor to multiply a SENT (downscaled) coordinate by to get a REAL pixel.

    >= 1.0 always; equals 1.0 when the screen already fits within MAX_DIM.
    """
    longest = max(width, height)
    if longest <= config.MAX_DIM:
        return 1.0
    return longest / config.MAX_DIM


def capture(monitor: int | None = None) -> tuple[bytes, int, int, int, int]:
    """Grab a monitor (default config.MONITOR) and downscale for the model.

    Returns: (image_bytes, sent_w, sent_h, real_w, real_h)
    """
    left, top, real_w, real_h = _monitor_geometry(monitor)
    with mss.MSS() as sct:
        raw = sct.grab({"left": left, "top": top, "width": real_w, "height": real_h})
    img = Image.frombytes("RGB", raw.size, raw.rgb)

    scale = _scale_for(real_w, real_h)
    if scale > 1.0:
        sent_w = max(1, round(real_w / scale))
        sent_h = max(1, round(real_h / scale))
        img = img.resize((sent_w, sent_h), Image.LANCZOS)
    else:
        sent_w, sent_h = real_w, real_h

    buf = io.BytesIO()
    if config.IMAGE_FORMAT == "jpeg":
        img.save(buf, format="JPEG", quality=80)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue(), sent_w, sent_h, real_w, real_h


def to_real(x: int, y: int, monitor: int | None = None) -> tuple[int, int]:
    """Map a model-space (downscaled) coordinate to a real absolute screen pixel.

    Adds the monitor's origin so multi-monitor offsets are respected. Must use
    the SAME monitor the screenshot was taken on.
    """
    left, top, real_w, real_h = _monitor_geometry(monitor)
    scale = _scale_for(real_w, real_h)
    rx = left + int(round(x * scale))
    ry = top + int(round(y * scale))
    # Clamp inside the monitor so a stray coordinate can't fly off-screen.
    rx = min(max(rx, left), left + real_w - 1)
    ry = min(max(ry, top), top + real_h - 1)
    return rx, ry


def image_mime() -> str:
    return "image/jpeg" if config.IMAGE_FORMAT == "jpeg" else "image/png"


if __name__ == "__main__":
    # Self-test: capture, report dims, write a file to eyeball.
    data, sw, sh, rw, rh = capture()
    out = "test_capture." + ("jpg" if config.IMAGE_FORMAT == "jpeg" else "png")
    with open(out, "wb") as f:
        f.write(data)
    print(f"Real monitor: {rw}x{rh}")
    print(f"Sent to model: {sw}x{sh}  (scale={_scale_for(rw, rh):.4f})")
    print(f"Wrote {out} ({len(data)} bytes)")

    # Coordinate round-trip sanity check across the sent image.
    print("\nRound-trip (sent center -> real):")
    cx, cy = sw // 2, sh // 2
    print(f"  sent ({cx},{cy}) -> real {to_real(cx, cy)}")
    print(f"  sent (0,0)      -> real {to_real(0, 0)}")
    print(f"  sent ({sw - 1},{sh - 1}) -> real {to_real(sw - 1, sh - 1)}")
