"""Priority matcher for the COA advisor. Given a list of Jobs and the ROE, splits them into a
DEFCON-ordered battle plan (`queue`) and ROE-disallowed jobs (`blocked`). No budget: nothing is
sized or forfeited — the runner stops on the real rate limit. Pure, stdlib only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .jobs import Job
from .roe import ROE


@dataclass
class COA:
    queue: List[Job] = field(default_factory=list)        # DEFCON-ordered run plan
    blocked: List[Job] = field(default_factory=list)      # ROE-disallowed (type)
    note: str = ""


def approval_required(job: Job, roe: ROE) -> bool:
    """High-impact jobs (defcon below the ROE gate) need explicit approval to run unattended."""
    return job.defcon < roe.auto_run_min_defcon


def weekly_reserve_pct(snapshot) -> Optional[float]:
    """Weekly budget still unspent, as a percent — shown as display CONTEXT, never a gate."""
    seven = (snapshot or {}).get("seven_day_pct")
    if seven is None:
        return None
    return max(0.0, 100.0 - float(seven))


def match(jobs: List[Job], roe: ROE) -> COA:
    """Sort eligible jobs by (defcon asc, value desc); route ROE-disallowed types to `blocked`."""
    eligible: List[Job] = []
    blocked: List[Job] = []
    for j in jobs:
        if roe.allowed_types is not None and j.type not in roe.allowed_types:
            blocked.append(j)
        else:
            eligible.append(j)
    eligible.sort(key=lambda j: (j.defcon, -j.value))

    if not eligible:
        note = "No eligible jobs (all blocked by the rules of engagement)." if blocked \
            else "No jobs proposed."
    else:
        n_appr = sum(1 for j in eligible if approval_required(j, roe))
        note = f"{len(eligible)} job(s) queued, most critical first"
        note += f" — {n_appr} need approval (DEFCON < {roe.auto_run_min_defcon})." if n_appr else "."
    return COA(queue=eligible, blocked=blocked, note=note)
