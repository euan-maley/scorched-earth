"""Pure burn-rate math. Stdlib only, no I/O — safe to call in the statusline hot path.

The model and derivation live in docs/the-math.md. In short: compare how much
*weekly* budget remains against how many 5-hour *windows* remain before the weekly
reset. If you couldn't spend the remaining weekly budget even by maxing every
remaining window, pacing wastes credits — go scorched earth (green light).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

WINDOW_SECONDS = 5 * 60 * 60  # 18000; the 5-hour rolling window

# target_per_window is "fraction of one full 5h window each remaining window should
# burn to spend the weekly budget evenly." >= GREEN means you can't spend it all even
# maxed out -> scorched earth. AMBER means burn hard, you're near the line.
GREEN_THRESHOLD = 1.0
AMBER_THRESHOLD = 0.70


@dataclass
class Snapshot:
    """A single live reading from the Claude Code statusline rate_limits payload."""

    now: int
    five_hour_pct: Optional[float] = None   # h:  rate_limits.five_hour.used_percentage
    five_hour_reset: Optional[int] = None   #     rate_limits.five_hour.resets_at (unix s)
    seven_day_pct: Optional[float] = None   # w:  rate_limits.seven_day.used_percentage
    seven_day_reset: Optional[int] = None   #     rate_limits.seven_day.resets_at (unix s)

    @property
    def has_weekly(self) -> bool:
        return self.seven_day_pct is not None and self.seven_day_reset is not None


@dataclass
class Recommendation:
    level: str                       # "green" | "amber" | "off" | "unknown"
    weekly_left: Optional[float]     # % of weekly budget remaining
    windows_left: Optional[float]    # fractional 5h-window capacity left before weekly reset
    target_per_window: Optional[float]  # fraction of a full window to burn each window (None if no R)
    burn_pct: Optional[float]        # display %: min(100, target_per_window*100)
    max_burnable_weekly: Optional[float]  # most of the weekly budget you could burn in the time left (%)
    hours_to_weekly_reset: Optional[float]
    hours_to_window_reset: Optional[float]
    r: Optional[float]               # R used for the call
    r_provisional: bool              # True if R is a guess, not measured
    reason: str                      # short human explanation


def windows_left(snap: Snapshot) -> Optional[float]:
    """Fractional 5h-window capacity remaining before the weekly reset.

    = unused capacity of the current window  +  full windows of time until weekly reset.
    """
    if not snap.has_weekly:
        return None
    # Unused capacity of the *current* 5h window, in window-units (0..1).
    h = snap.five_hour_pct if snap.five_hour_pct is not None else 0.0
    current_remaining = max(0.0, (100.0 - h) / 100.0)
    # Time from when the current window resets until the weekly reset -> further windows.
    if snap.five_hour_reset is not None:
        tail_seconds = max(0, snap.seven_day_reset - snap.five_hour_reset)
    else:
        # No window reset known: approximate the tail from now + one window.
        tail_seconds = max(0, snap.seven_day_reset - (snap.now + WINDOW_SECONDS))
    tail_windows = tail_seconds / WINDOW_SECONDS
    return current_remaining + tail_windows


def compute(snap: Snapshot, r: Optional[float], r_provisional: bool = False) -> Recommendation:
    """Turn a snapshot + calibration R into a recommendation.

    `r` is the fraction of the *weekly* cap that one full 5h window burns (e.g. 0.07).
    Pass None when no estimate exists yet -> level "unknown".
    """
    weekly_left = None if snap.seven_day_pct is None else max(0.0, 100.0 - snap.seven_day_pct)
    wl = windows_left(snap)

    hrs_week = (
        max(0.0, (snap.seven_day_reset - snap.now) / 3600.0)
        if snap.seven_day_reset is not None
        else None
    )
    hrs_window = (
        max(0.0, (snap.five_hour_reset - snap.now) / 3600.0)
        if snap.five_hour_reset is not None
        else None
    )

    def base(level, target, burn, maxb, reason):
        return Recommendation(
            level=level,
            weekly_left=weekly_left,
            windows_left=wl,
            target_per_window=target,
            burn_pct=burn,
            max_burnable_weekly=maxb,
            hours_to_weekly_reset=hrs_week,
            hours_to_window_reset=hrs_window,
            r=r,
            r_provisional=r_provisional,
            reason=reason,
        )

    if weekly_left is None or wl is None:
        return base("unknown", None, None, None, "No weekly usage data yet.")

    if weekly_left <= 0.5:
        return base("off", 0.0, 0.0, None,
                    "Mission accomplished, soldier. Burned to the last drop, and you cut it close. Rest up for reinforcements.")

    # Weekly reset is essentially here but budget remains -> burn it now.
    if wl <= 0.0:
        return base("green", float("inf"), 100.0, 0.0,
                    "Reinforcements are almost here. Give them everything you've got, don't hold back. Last man standing.")

    if r is None or r <= 0:
        return base("unknown", None, None, None,
                    "Recon's not in yet. Need more data before I can call it.")

    max_burnable = wl * r * 100.0                       # most of weekly you could burn in time left
    target = (weekly_left / wl) / (r * 100.0)           # fraction of one window per window
    burn = min(100.0, target * 100.0)

    if target >= GREEN_THRESHOLD:
        reason = (
            f"Full assault clears just ~{max_burnable:.0f}% before reset; {weekly_left:.0f}% sits "
            f"in reserve, forfeit when the clock runs out. Empty the magazine. That's an order."
        )
        return base("green", target, burn, max_burnable, reason)
    if target >= AMBER_THRESHOLD:
        return base("amber", target, burn, max_burnable,
                    f"Sustain ~{burn:.0f}% each window and it's all spent by reset. Hold the line.")
    return base("off", target, burn, max_burnable,
                f"Reserves are deep. Even a relaxed ~{burn:.0f}% per window spends it all by reset. "
                f"That's the easy pace, not a cap. Push harder anytime.")
