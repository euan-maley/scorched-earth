"""Truecolor fire-gradient text with a traveling wave.

Each character is colored along a flame ramp (red -> orange -> yellow), and a phase
offset shifts the wave so the colors flow across the letters when phase advances over
time. Truecolor (24-bit) when the terminal supports it, a 256-color fire ramp otherwise,
and a plain bold-orange fallback if neither.

Pure functions except `supports_truecolor()` / the optional time-based phase, which the
caller supplies.
"""

from __future__ import annotations

import math
import os

RESET = "\033[0m"

# 256-color fire ramp (xterm): deep red -> orange -> yellow -> pale.
_RAMP_256 = [196, 202, 208, 214, 220, 226, 220, 214, 208, 202]


def supports_truecolor() -> bool:
    return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = [
        (v, t, p), (q, v, p), (p, v, t),
        (p, q, v), (t, p, v), (v, p, q),
    ][i % 6]
    return int(r * 255), int(g * 255), int(b * 255)


def _flame_rgb(pos: float) -> tuple[int, int, int]:
    """pos is a phase in radians. Hue oscillates in the red->yellow band, with a small
    brightness flicker so it reads like fire rather than a flat rainbow."""
    hue_deg = 27 + 22 * math.sin(pos)          # ~5..49 degrees: red, orange, yellow
    val = 0.86 + 0.14 * math.sin(pos * 1.7 + 1.0)
    return _hsv_to_rgb(hue_deg / 360.0, 1.0, max(0.0, min(1.0, val)))


def fire(text: str, phase: float = 0.0, cycles: float = 1.3, truecolor=None) -> str:
    """Return `text` colored as a flowing flame. `phase` (radians) animates the wave."""
    if truecolor is None:
        truecolor = supports_truecolor()
    n = max(1, len(text))
    out = []
    for i, ch in enumerate(text):
        pos = (i / n) * (2 * math.pi * cycles) - phase
        if truecolor:
            r, g, b = _flame_rgb(pos)
            out.append(f"\033[1;38;2;{r};{g};{b}m{ch}")
        else:
            idx = _RAMP_256[int((i - phase * 1.6) % len(_RAMP_256))]
            out.append(f"\033[1;38;5;{idx}m{ch}")
    out.append(RESET)
    return "".join(out)
