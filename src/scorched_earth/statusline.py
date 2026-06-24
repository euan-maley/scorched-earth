"""Statusline entry point. Reads the Claude Code statusline JSON on stdin, samples for
calibration, persists state, and prints a compact light token (with real ANSI color) to
stdout. Prints nothing when there's no actionable signal, so the statusline stays clean.

Driven from a host statusline via:  printf '%s' "$DATA" | python3 -m scorched_earth.statusline

Never raises into the host statusline: any failure prints nothing and exits 0.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time

# Real ANSI escapes (the host captures these verbatim and re-emits them).
GREEN = "\033[1;32m"   # bold green
AMBER = "\033[33m"
RESET = "\033[0m"

# Styles: fire (animated flames, the installed default seeded by the hook/installer), emoji,
# text (colored words, no emoji), minimal (just a dot). `_resolve_style` falls back to emoji
# only if the style file is unset/missing.
STYLES = {
    "emoji": {"green": f"🟢 {GREEN}BURN IT ALL{RESET}", "amber": "🟡 {amber}"},
    "text": {"green": f"{GREEN}BURN IT ALL{RESET}", "amber": "{amber}"},
    "minimal": {"green": f"{GREEN}●{RESET}", "amber": f"{AMBER}●{RESET}"},
}


def token(rec, style: str) -> str:
    # Fire: the green light stays (identity) but "BURN IT ALL" burns. The phase comes from
    # wall-clock, so the flame flows each time the statusline refreshes (cadence is set by
    # Claude Code, so it shimmers rather than animating smoothly).
    if style == "fire":
        if rec.level == "green":
            from . import gradient
            phase = (time.time() * 2.4) % (2 * math.pi)
            return "🔥 " + gradient.fire("BURN IT ALL", phase=phase)
        if rec.level == "amber" and rec.burn_pct is not None:
            return f"🟡 {AMBER}burn {rec.burn_pct:.0f}%{RESET}"
        return ""

    s = STYLES.get(style, STYLES["emoji"])
    if rec.level == "green":
        return s["green"]
    if rec.level == "amber" and rec.burn_pct is not None:
        amber_txt = f"{AMBER}burn {rec.burn_pct:.0f}%{RESET}"
        return s["amber"].format(amber=amber_txt)
    return ""  # off / unknown -> nothing


def _resolve_style() -> str:
    """Style precedence: env var > config file > default. Lets the installer set it by
    writing ~/.claude/scorched-earth/style without touching the host statusline."""
    env = os.environ.get("SCORCHED_STYLE")
    if env:
        return env.strip()
    try:
        path = os.path.expanduser("~/.claude/scorched-earth/style")
        with open(path) as f:
            val = f.read().strip()
            if val:
                return val
    except OSError:
        pass
    return "emoji"


def _notify(title: str, subtitle: str, msg: str) -> bool:
    """Best-effort desktop notification. macOS via osascript, Linux via notify-send.

    All strings come from our own formatted numbers/literals (no user/network input), and
    every command is run via an argv list (no shell), so there's no injection surface.
    Returns True if a notifier was invoked."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{title}" subtitle "{subtitle}"'],
            check=False, capture_output=True,
        )
        return True
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", f"{title} — {subtitle}", msg],
                       check=False, capture_output=True)
        return True
    return False


def _maybe_notify_forecast(fc, weekly_reset) -> None:
    """Fire a single preemptive desktop nudge per weekly cycle when habits project that
    the user will leave meaningful budget unused — only once the profile is trustworthy.
    Best-effort (macOS/Linux); never raises into the caller."""
    try:
        if not fc.preemptive or fc.confidence not in ("medium", "high"):
            return
        marker = os.path.expanduser("~/.claude/scorched-earth/fc-notified")
        try:
            with open(marker) as f:
                if f.read().strip() == str(weekly_reset):
                    return  # already nudged for this weekly cycle
        except OSError:
            pass
        left = fc.projected_leftover or 0
        end = fc.projected_end_used or 0
        msg = (f"Tracking to {end:.0f}% used — {left:.0f}% left to burn before reset. "
               f"Deploy it.")
        if _notify("Scorched Earth", "Torch it all. Leave them nothing.", msg):
            with open(marker, "w") as f:
                f.write(str(weekly_reset))
    except Exception:
        return


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            return 0
        from . import state as st  # imported lazily so an import error can't break the bar
        result = st.update_from_statusline(data)
        _maybe_notify_forecast(result.forecast, result.snap.seven_day_reset)
        style = _resolve_style()
        if style == "off":
            return 0
        out = token(result.rec, style)
        if out:
            sys.stdout.write(out)
    except Exception:
        return 0  # degrade to empty; the statusline must always render
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
