"""Budget-to-job matcher: the tier-and-fill core. Given the current-window headroom and a list
of Jobs, annotates every job as fits / over_budget / blocked — nothing is forfeited.
Pure, stdlib only. Reads no files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .jobs import Job
from .roe import ROE

_EPS = 1e-9


@dataclass
class COA:
    queue: List[Job] = field(default_factory=list)          # fits within headroom, run order
    over_budget: List[Job] = field(default_factory=list)    # eligible but beyond headroom — queue anyway
    blocked: List[Job] = field(default_factory=list)        # ROE-disallowed (type / per-job cap)
    headroom_windows: float = 0.0                           # current-window headroom used for the split
    weekly_reserve_pct: float = 0.0                         # context only
    fits_windows: float = 0.0                               # sum of queue est_windows
    note: str = ""


def window_headroom(snapshot) -> Optional[float]:
    """Unused capacity of the CURRENT 5-hour window, in window-units (0..1.0). This is the COA
    execution headroom — NOT windows-until-weekly-reset. None when five_hour_pct is absent."""
    five = (snapshot or {}).get("five_hour_pct")
    if five is None:
        return None
    return max(0.0, (100.0 - float(five)) / 100.0)


def weekly_reserve_pct(snapshot) -> Optional[float]:
    """Weekly budget still unspent, as a percent — shown as CONTEXT next to headroom, never a gate."""
    seven = (snapshot or {}).get("seven_day_pct")
    if seven is None:
        return None
    return max(0.0, 100.0 - float(seven))


def match(headroom: float, jobs: List[Job], roe: ROE, *, weekly_reserve_pct: float = 0.0) -> COA:
    """Annotate every job against the current-window headroom: fits / over_budget / blocked.
    Nothing is forfeited for budget — `over_budget` jobs are still queueable. ROE-disallowed
    jobs (type / per-job cap) are `blocked` (distinct). roe.max_windows, if set, lowers the
    fit threshold but never drops a job."""
    cap = max(0.0, headroom)
    if roe.max_windows is not None:
        cap = min(cap, roe.max_windows)

    eligible: List[Job] = []
    blocked: List[Job] = []
    for j in jobs:
        if roe.allowed_types is not None and j.type not in roe.allowed_types:
            blocked.append(j)
            continue
        if roe.per_job_max_windows is not None and j.est_windows > roe.per_job_max_windows:
            blocked.append(j)
            continue
        eligible.append(j)

    eligible.sort(key=lambda j: (j.value / j.est_windows if j.est_windows > 0 else 0.0, j.value),
                  reverse=True)

    queue: List[Job] = []
    over: List[Job] = []
    spent = 0.0
    for j in eligible:
        if spent + j.est_windows <= cap + _EPS:
            queue.append(j)
            spent += j.est_windows
        else:
            over.append(j)

    if not eligible:
        note = "No eligible jobs (all blocked by the rules of engagement)." if blocked \
            else "No jobs proposed."
    elif not queue:
        note = (f"~{cap:.2f} window free now — every job is bigger than that. "
                f"Queue what's worth it; it runs until the real limit.")
    else:
        note = (f"{len(queue)} job(s) fit ~{cap:.2f} window free now"
                + (f", {len(over)} over budget (queue anyway)." if over else "."))
    return COA(queue=queue, over_budget=over, blocked=blocked,
               headroom_windows=round(cap, 4), weekly_reserve_pct=weekly_reserve_pct,
               fits_windows=round(spent, 4), note=note)
