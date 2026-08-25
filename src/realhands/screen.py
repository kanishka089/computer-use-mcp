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

from . import config


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


PATCH = 28  # Claude bills vision in 28x28 patches; see config.PATCH_ALIGN.


def _target_size(real_w: int, real_h: int) -> tuple[int, int]:
    """The exact (width, height) we send to the model for this monitor.

    Single source of truth: capture() resizes to it and to_real() derives its
    scale factors from it, so a coordinate never depends on which screenshot ran
    last. Patch alignment rounds each axis DOWN to a whole 28px patch, which
    drops a sliver of pixels (<28px) to avoid paying for a partial patch row or
    column. Each axis rounds independently, so the scale can be very slightly
    non-uniform (<2.2%) — harmless, because to_real() maps each axis with its own
    factor rather than assuming a single one.
    """
    longest = max(real_w, real_h)
    if longest > config.MAX_DIM:
        scale = longest / config.MAX_DIM
        sent_w = max(1, round(real_w / scale))
        sent_h = max(1, round(real_h / scale))
    else:
        sent_w, sent_h = real_w, real_h

    if config.PATCH_ALIGN:
        # Only round down when there is a whole patch to keep on that axis.
        if sent_w >= PATCH:
            sent_w = (sent_w // PATCH) * PATCH
        if sent_h >= PATCH:
            sent_h = (sent_h // PATCH) * PATCH
    return sent_w, sent_h


def visual_tokens(width: int, height: int) -> int:
    """What this image costs Claude: ceil(w/28) * ceil(h/28) visual tokens."""
    return -(-width // PATCH) * -(-height // PATCH)


def _encode(img: "Image.Image") -> bytes:
    buf = io.BytesIO()
    if config.IMAGE_FORMAT == "jpeg":
        img.save(buf, format="JPEG", quality=80)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


def grab(monitor: int | None = None) -> tuple["Image.Image", int, int]:
    """Grab a monitor and return the model-sized PIL image + its real dimensions."""
    left, top, real_w, real_h = _monitor_geometry(monitor)
    with mss.MSS() as sct:
        raw = sct.grab({"left": left, "top": top, "width": real_w, "height": real_h})
    img = Image.frombytes("RGB", raw.size, raw.rgb)

    sent_w, sent_h = _target_size(real_w, real_h)
    if (sent_w, sent_h) != (real_w, real_h):
        img = img.resize((sent_w, sent_h), Image.LANCZOS)
    return img, real_w, real_h


def capture(monitor: int | None = None) -> tuple[bytes, int, int, int, int]:
    """Grab a monitor (default config.MONITOR) and downscale for the model.

    Returns: (image_bytes, sent_w, sent_h, real_w, real_h)
    """
    img, real_w, real_h = grab(monitor)
    return _encode(img), img.width, img.height, real_w, real_h


def to_real(x: int, y: int, monitor: int | None = None) -> tuple[int, int]:
    """Map a model-space (downscaled) coordinate to a real absolute screen pixel.

    Adds the monitor's origin so multi-monitor offsets are respected. Must use
    the SAME monitor the screenshot was taken on.
    """
    left, top, real_w, real_h = _monitor_geometry(monitor)
    sent_w, sent_h = _target_size(real_w, real_h)
    rx = left + int(round(x * (real_w / sent_w)))
    ry = top + int(round(y * (real_h / sent_h)))
    # Clamp inside the monitor so a stray coordinate can't fly off-screen.
    rx = min(max(rx, left), left + real_w - 1)
    ry = min(max(ry, top), top + real_h - 1)
    return rx, ry


def image_mime() -> str:
    return "image/jpeg" if config.IMAGE_FORMAT == "jpeg" else "image/png"


# --- change detection -------------------------------------------------------
# The most expensive thing this server can do is send a screenshot the model has
# already seen. A full 1260x700 frame costs ~1125 visual tokens and is re-sent on
# every later turn as conversation history, so a redundant one is not a one-off
# charge. We keep the last frame we actually sent (per monitor) and skip the
# image when nothing meaningful moved.
#
# Equality is useless here: a real desktop never produces two identical frames
# (clock, text caret, hover states, antialiasing all jitter), so we measure the
# FRACTION of materially-different pixels instead.

_last_sent: dict[int, "Image.Image"] = {}
_skips: dict[int, int] = {}


def _changed_fraction(a: "Image.Image", b: "Image.Image") -> float:
    """Fraction of pixels that differ by more than a just-noticeable amount."""
    from PIL import ImageChops

    diff = ImageChops.difference(a, b).convert("L")
    # Ignore sub-threshold noise (compression/antialias jitter), then count.
    mask = diff.point(lambda p: 255 if p > 8 else 0)
    hist = mask.histogram()
    return hist[255] / float(a.width * a.height)


def capture_smart(
    monitor: int | None = None, force: bool = False
) -> tuple[bytes | None, int, int, float]:
    """Capture, but return no bytes when the screen is effectively unchanged.

    Returns (image_bytes_or_None, sent_w, sent_h, changed_fraction). A None
    image means "the last screenshot you were sent is still accurate". Forced
    every config.MAX_SKIPS calls so the model can never drift too far from the
    real screen if it lost the earlier image.
    """
    key = config.MONITOR if monitor is None else int(monitor)
    img, _, _ = grab(monitor)
    prev = _last_sent.get(key)

    changed = 1.0
    if prev is not None and prev.size == img.size:
        changed = _changed_fraction(prev, img)

    skips = _skips.get(key, 0)
    suppress = (
        not force
        and config.CHANGE_THRESHOLD > 0
        and prev is not None
        and changed < config.CHANGE_THRESHOLD
        and skips < config.MAX_SKIPS
    )
    if suppress:
        _skips[key] = skips + 1
        return None, img.width, img.height, changed

    _last_sent[key] = img
    _skips[key] = 0
    return _encode(img), img.width, img.height, changed


if __name__ == "__main__":
    # Self-test: capture, report dims, write a file to eyeball.
    data, sw, sh, rw, rh = capture()
    out = "test_capture." + ("jpg" if config.IMAGE_FORMAT == "jpeg" else "png")
    with open(out, "wb") as f:
        f.write(data)
    print(f"Real monitor: {rw}x{rh}")
    print(f"Sent to model: {sw}x{sh}  (scale x{rw / sw:.4f} y{rh / sh:.4f})")
    print(f"Visual tokens: {visual_tokens(sw, sh)}  ({sw // 28}x{sh // 28} patches)")
    print(f"Wrote {out} ({len(data)} bytes)")

    # Coordinate round-trip sanity check across the sent image.
    print("\nRound-trip (sent center -> real):")
    cx, cy = sw // 2, sh // 2
    print(f"  sent ({cx},{cy}) -> real {to_real(cx, cy)}")
    print(f"  sent (0,0)      -> real {to_real(0, 0)}")
    print(f"  sent ({sw - 1},{sh - 1}) -> real {to_real(sw - 1, sh - 1)}")
