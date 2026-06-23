"""Self-measure R = fraction of the weekly cap that one full 5h window burns.

R is a plan constant (ratio of the 5h cap to the weekly cap). We don't hardcode it;
we measure it from the user's own snapshots. Between two readings in the *same* window
and *same* weekly period, the 5h-used % rose by dh percentage-points and the weekly-used
% rose by dw percentage-points. Since a full window is 100 pp of h and burns R of the
week (= 100R pp of w), we have dw = R * dh, so R = dw / dh.

A rolling median over clean pairs is stable and self-correcting. Pure functions only.
"""

from __future__ import annotations

from statistics import median
from typing import List, Optional

# Rough fallback until enough real data exists: a maxed window ~ 5% of the week
# (~20 full windows per weekly budget). Used only when flagged provisional.
DEFAULT_R = 0.05

MIN_DH = 2.0       # ignore pairs with < 2 pp of window movement (noise / div blow-up)
MIN_PAIRS = 3      # need this many clean pairs before R is considered measured
MAX_SAMPLES = 300  # ring-buffer cap on stored samples


def append_sample(samples: List[dict], snap_dict: dict) -> List[dict]:
    """Append a reading and trim. Drops history when the weekly period rolls over.

    `snap_dict` keys: now, five_hour_pct, five_hour_reset, seven_day_pct, seven_day_reset.
    """
    if snap_dict.get("seven_day_pct") is None or snap_dict.get("seven_day_reset") is None:
        return samples  # nothing useful to record

    out = list(samples)
    # If the weekly window reset since the last sample, the old samples are a different
    # budget period — start fresh so deltas never straddle a reset.
    if out:
        last = out[-1]
        if last.get("seven_day_reset") != snap_dict.get("seven_day_reset"):
            out = []

    # De-dupe identical back-to-back readings (statusline refreshes faster than usage moves).
    if out:
        last = out[-1]
        if (
            last.get("five_hour_pct") == snap_dict.get("five_hour_pct")
            and last.get("seven_day_pct") == snap_dict.get("seven_day_pct")
        ):
            return out

    out.append(
        {
            "now": snap_dict.get("now"),
            "five_hour_pct": snap_dict.get("five_hour_pct"),
            "five_hour_reset": snap_dict.get("five_hour_reset"),
            "seven_day_pct": snap_dict.get("seven_day_pct"),
            "seven_day_reset": snap_dict.get("seven_day_reset"),
        }
    )
    if len(out) > MAX_SAMPLES:
        out = out[-MAX_SAMPLES:]
    return out


def _pair_estimates(samples: List[dict]) -> List[float]:
    """R estimates from consecutive same-window, same-week pairs with real movement."""
    ests: List[float] = []
    for a, b in zip(samples, samples[1:]):
        if a.get("five_hour_pct") is None or b.get("five_hour_pct") is None:
            continue
        if a.get("seven_day_pct") is None or b.get("seven_day_pct") is None:
            continue
        # Same weekly period.
        if a.get("seven_day_reset") != b.get("seven_day_reset"):
            continue
        # Same 5h window (a reset would drop the 5h %); require the window reset to match
        # when known, else fall back to "h didn't decrease".
        if a.get("five_hour_reset") is not None and b.get("five_hour_reset") is not None:
            if a["five_hour_reset"] != b["five_hour_reset"]:
                continue
        dh = b["five_hour_pct"] - a["five_hour_pct"]
        dw = b["seven_day_pct"] - a["seven_day_pct"]
        if dh < MIN_DH or dw < 0:
            continue
        r = dw / dh
        # Sanity clamp: a window can't plausibly be more than the whole week or absurdly tiny.
        if 0 < r <= 1.0:
            ests.append(r)
    return ests


def estimate_r(samples: List[dict]) -> tuple[float, bool]:
    """Return (R, provisional). provisional=True means it's the fallback, not measured."""
    ests = _pair_estimates(samples)
    if len(ests) >= MIN_PAIRS:
        return median(ests), False
    if ests:
        # Some signal but not enough to trust — blend toward the fallback, still provisional.
        return median(ests), True
    return DEFAULT_R, True
