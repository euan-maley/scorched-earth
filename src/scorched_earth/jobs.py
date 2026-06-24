"""Job schema for the COA advisor: the expensive-work items a repo scan produces and the
budget matcher consumes. Pure, stdlib only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

# Upper bounds (in 5h-window-units) for the human-readable tier label. Above L -> XL.
_TIER_BOUNDS = (("S", 0.5), ("M", 1.5), ("L", 3.0))


def tier_for(est_windows: float) -> str:
    for name, upper in _TIER_BOUNDS:
        if est_windows <= upper:
            return name
    return "XL"


@dataclass
class Job:
    id: str
    repo: str
    title: str
    type: str
    est_windows: float            # rough cost in window-units, emitted by the scan agent
    value: float                  # the scan agent's worth ranking, drives priority
    rationale: str = ""
    launch: str = ""              # prompt/command to run it (Phase 1 hands this to the user)
    status: str = "proposed"      # proposed | queued | done (Phase 2+ uses this)

    @property
    def tier(self) -> str:
        return tier_for(self.est_windows)


def parse_jobs(data, repo: str = "") -> List[Job]:
    """Build Jobs from a list of dicts (e.g. parsed .scorched/jobs.json). Entries missing the
    matcher inputs (id, est_windows, value) are skipped rather than crashing."""
    out: List[Job] = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        if d.get("id") is None or d.get("est_windows") is None or d.get("value") is None:
            continue
        out.append(Job(
            id=str(d["id"]),
            repo=d.get("repo") or repo,
            title=d.get("title", ""),
            type=d.get("type", "other"),
            est_windows=float(d["est_windows"]),
            value=float(d["value"]),
            rationale=d.get("rationale", ""),
            launch=d.get("launch", ""),
            status=d.get("status", "proposed"),
        ))
    return out
