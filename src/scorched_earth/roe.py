"""Rules of Engagement: the confines that bound the advisor (and, later, the executor).
Three families: cost, task, goal. Pure, stdlib only."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import List, Optional


@dataclass
class ROE:
    # cost rules
    max_windows: Optional[float] = None             # cap total burn per COA (window-units)
    per_job_max_windows: Optional[float] = None     # reject any single job bigger than this
    min_weekly_left: float = 0.0                    # don't propose unless weekly-left above this
    # task rules
    allowed_types: Optional[List[str]] = None       # None = all types allowed
    # runner rules (Phase 2a — bound the autonomous executor)
    unattended_types: Optional[List[str]] = None    # types allowed to run unattended; None = SAFE default
    test_cmd: Optional[str] = None                  # post-job verification gate command
    setup_cmd: Optional[str] = None                 # dependency pre-warm command (runner-run, with network)
    # goal rules
    exclude_paths: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)


DEFAULT_ROE = ROE()


def roe_from_dict(d, base: ROE = DEFAULT_ROE) -> ROE:
    """Overlay the keys present in `d` onto `base`. Unknown keys are ignored."""
    d = d or {}
    names = {f.name for f in fields(ROE)}
    kwargs = {f.name: getattr(base, f.name) for f in fields(ROE)}
    for k, v in d.items():
        if k in names and v is not None:
            kwargs[k] = v
    return ROE(**kwargs)


def merge_roe(base: ROE, override: ROE) -> ROE:
    """Per-repo ROE over global default. A field on `override` wins only if it differs from
    the dataclass default (i.e. it was actually set)."""
    blank = ROE()
    kwargs = {}
    for f in fields(ROE):
        ov = getattr(override, f.name)
        kwargs[f.name] = ov if ov != getattr(blank, f.name) else getattr(base, f.name)
    return ROE(**kwargs)
