"""Budget-to-job matcher: the tier-and-fill core. Given the available burn (window-units) and
a list of Jobs, greedily select the highest value-per-window jobs that fit, honoring the ROE
cost and task rules. Pure, stdlib only. Reads no files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .jobs import Job
from .roe import ROE

_EPS = 1e-9


@dataclass
class COA:
    queue: List[Job] = field(default_factory=list)      # selected, in run order
    skipped: List[Job] = field(default_factory=list)    # didn't fit or disallowed
    envelope_windows: float = 0.0                       # capacity used for matching
    spent_windows: float = 0.0                          # sum of selected est_windows
    note: str = ""


def match(available_windows: float, jobs: List[Job], roe: ROE) -> COA:
    envelope = max(0.0, available_windows)
    if roe.max_windows is not None:
        envelope = min(envelope, roe.max_windows)

    eligible: List[Job] = []
    skipped: List[Job] = []
    for j in jobs:
        if roe.allowed_types is not None and j.type not in roe.allowed_types:
            skipped.append(j)
            continue
        if roe.per_job_max_windows is not None and j.est_windows > roe.per_job_max_windows:
            skipped.append(j)
            continue
        eligible.append(j)

    # Highest value-per-window first; ties by raw value.
    eligible.sort(key=lambda j: (j.value / j.est_windows if j.est_windows > 0 else 0.0, j.value),
                  reverse=True)

    queue: List[Job] = []
    spent = 0.0
    for j in eligible:
        if spent + j.est_windows <= envelope + _EPS:
            queue.append(j)
            spent += j.est_windows
        else:
            skipped.append(j)

    if envelope <= _EPS:
        note = "Nothing to burn right now: no available capacity."
    elif not queue:
        note = "Budget available but no eligible jobs fit the rules of engagement."
    else:
        note = f"Queued {len(queue)} job(s), ~{spent:.1f} of {envelope:.1f} windows."
    return COA(queue=queue, skipped=skipped, envelope_windows=envelope,
               spent_windows=spent, note=note)
