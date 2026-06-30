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
# burn to spend the weekly budget evenly." >= MAX means you can't spend it all even
# maxed out -> scorched earth. PUSH means burn hard, you're near the line.
MAX_THRESHOLD = 1.0
PUSH_THRESHOLD = 0.70

# "hold your fire" (ease) gentleness knob: warn only when, at the recent actual pace, you'd
# run the weekly budget dry leaving more than this many usable windows stranded before the
# reset. ~one active day of lockout. Twitchy ~1, Relaxed ~5; default Balanced = 3.
EASE_IDLE_WINDOWS = 3.0

# Canonical war-general verdict per status. The CLI headline and the HTML sitrep banner both
# read this, so the voice can't drift between surfaces. The reason sentences live in compute().
# Keys are the firing ladder: max -> push -> steady, ease (off the trigger), done (after-action).
HEADLINE = {
    "max": "Torch it all. Leave them nothing.",
    "push": "Clear shot, take it. Hold the line near full throttle.",
    "steady": "Eyes on the target. Dead on pace, hold steady.",
    "ease": "Hold your fire. Save rounds for tomorrow or you'll run dry before reinforcements.",
    "done": "Good job, soldier. Burned to the last drop, rest up for reinforcements.",
    "unknown": "No read yet. Hold your horses.",
}


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

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        """Build from a persisted/untrusted dict, ignoring unknown keys and filling gaps.

        Lets the CLI and report read a state.json written by a different version (extra or
        missing fields) without a TypeError crash.
        """
        return cls(
            now=d.get("now") or 0,
            five_hour_pct=d.get("five_hour_pct"),
            five_hour_reset=d.get("five_hour_reset"),
            seven_day_pct=d.get("seven_day_pct"),
            seven_day_reset=d.get("seven_day_reset"),
        )


@dataclass
class Recommendation:
    level: str                       # "max" | "push" | "steady" | "ease" | "done" | "unknown"
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


def windows_left(snap: Snapshot, active_fraction: float = 1.0) -> Optional[float]:
    """Fractional 5h-window capacity remaining before the weekly reset.

    = unused capacity of the current window  +  full windows of time until weekly reset.
    The future tail is scaled by `active_fraction` (hours/day you're actually around to burn,
    over 24), since you can't spend a window you're asleep for. The current window isn't
    discounted: you're awake in it now.
    """
    if not snap.has_weekly:
        return None
    # Unused capacity of the *current* 5h window, in window-units (0..1).
    h = snap.five_hour_pct if snap.five_hour_pct is not None else 0.0
    current_remaining = max(0.0, (100.0 - h) / 100.0)
    # ...but you can only spend it in the time left before the weekly reset, and capacity
    # burns at most one window's worth per 5h. If the current window straddles the weekly
    # reset (reset lands mid-window), cap the credit by the time actually remaining so we
    # don't count next-week capacity as this week's.
    secs_to_weekly = max(0, snap.seven_day_reset - snap.now)
    current_remaining = min(current_remaining, secs_to_weekly / WINDOW_SECONDS)
    # Time from when the current window resets until the weekly reset -> further windows.
    if snap.five_hour_reset is not None:
        tail_seconds = max(0, snap.seven_day_reset - snap.five_hour_reset)
    else:
        # No window reset known: approximate the tail from now + one window.
        tail_seconds = max(0, snap.seven_day_reset - (snap.now + WINDOW_SECONDS))
    tail_windows = tail_seconds / WINDOW_SECONDS
    return current_remaining + tail_windows * active_fraction


def compute(snap: Snapshot, r: Optional[float], r_provisional: bool = False,
            active_fraction: float = 1.0,
            recent_per_window: Optional[float] = None) -> Recommendation:
    """Turn a snapshot + calibration R into a recommendation.

    `r` is the fraction of the *weekly* cap that one full 5h window burns (e.g. 0.07).
    `active_fraction` discounts future windows for sleep/inactivity (1.0 = count them all).
    `recent_per_window` is your *measured recent* burn (% of weekly per window). When given,
    a `push`/`steady` call can be overridden to `ease` ("hold your fire") if that pace would
    run the weekly budget dry leaving > EASE_IDLE_WINDOWS usable windows stranded before the
    reset. Kept pure: the caller (statusline) measures the rate from habits and passes it in.
    Pass None for r when no estimate exists yet -> level "unknown".
    """
    weekly_left = None if snap.seven_day_pct is None else max(0.0, 100.0 - snap.seven_day_pct)
    wl = windows_left(snap, active_fraction)

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
        return base("done", 0.0, 0.0, None,
                    "Good job, soldier. Burned to the last drop, and you cut it close. Rest up for reinforcements.")

    # Weekly reset is essentially here but budget remains -> burn it now.
    if wl <= 0.0:
        return base("max", float("inf"), 100.0, 0.0,
                    "Reinforcements are almost here. Give them everything you've got, don't hold back. Last man standing.")

    if r is None or r <= 0:
        return base("unknown", None, None, None,
                    "Recon's not in yet. Need more data before I can call it.")

    max_burnable = wl * r * 100.0                       # most of weekly you could burn in time left
    target = (weekly_left / wl) / (r * 100.0)           # fraction of one window per window
    burn = min(100.0, target * 100.0)

    if target >= MAX_THRESHOLD:
        reason = (
            f"Full assault clears just ~{max_burnable:.0f}% before reset; {weekly_left:.0f}% sits "
            f"in reserve, forfeit when the clock runs out. Empty the magazine. That's an order."
        )
        return base("max", target, burn, max_burnable, reason)

    # push / steady territory. A measured recent overpace can override to "hold your fire":
    # at that rate you'd run the budget dry leaving usable windows stranded before reset.
    # Self-disengaging: as wl -> 0 near the reset, idle_windows can't exceed the threshold, so
    # it never interrupts burn-it-all. Mutually exclusive with `max` (can't run dry if maxed).
    if recent_per_window is not None and recent_per_window > 0:
        windows_to_dry = weekly_left / recent_per_window
        idle_windows = wl - windows_to_dry
        if idle_windows > EASE_IDLE_WINDOWS:
            sustainable = weekly_left / wl  # % of weekly per window to spend evenly
            return base("ease", target, burn, max_burnable,
                        f"Hold your fire. At this pace you'll run dry ~{idle_windows:.0f} windows "
                        f"before reinforcements. Ease to ~{sustainable:.0f}% a window to hold the "
                        f"line to reset.")

    if target >= PUSH_THRESHOLD:
        return base("push", target, burn, max_burnable,
                    f"Clear shot, take it. Sustain ~{burn:.0f}% each window and it's all spent by "
                    f"reset. Hold the line.")
    return base("steady", target, burn, max_burnable,
                f"Eyes on the target. Even a relaxed ~{burn:.0f}% per window spends it all by reset. "
                f"Dead on pace, hold steady. Push harder anytime.")
