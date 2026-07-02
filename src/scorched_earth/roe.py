"""Rules of Engagement: the confines that bound the advisor (and, later, the executor).
Three families: cost, task, goal. Pure, stdlib only."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import List, Optional


@dataclass
class ROE:
    # cost / run-length rules
    min_weekly_left: float = 0.0                    # don't propose unless weekly-left above this (real signal)
    max_jobs: Optional[int] = None                  # optional run cap: stop after N jobs (off by default)
    # task rules
    allowed_types: Optional[List[str]] = None       # None = all types allowed
    auto_run_min_defcon: int = 3                     # jobs with defcon < this need explicit approval to run
    # runner rules (bound the autonomous executor)
    unattended_types: Optional[List[str]] = None    # types allowed to run unattended; None = SAFE default
    test_cmd: Optional[str] = None                  # post-job verification gate command
    setup_cmd: Optional[str] = None                 # dependency pre-warm command (runner-run, with network)
    # execution-mode rules (Phase 3): how a job runs, and the attended / roadblock leash
    run_mode: str = "headless"                      # headless | takeover | session (global default + per-repo)
    context_cmd: Optional[str] = None               # attended pre-task command, e.g. "/kerd:switch in" (freeform)
    attended_branch: bool = False                   # attended jobs get a scorched/<id> branch vs. current branch
    roadblock_idle_secs: int = 600                  # headless: seconds of silence before a job is flagged stuck
    advise_on_roadblock: bool = True                # try the advising agent to auto-solve before pausing
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
