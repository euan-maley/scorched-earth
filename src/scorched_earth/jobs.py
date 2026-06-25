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


# Coarse depth(1-10) -> internal window-cost band. The agent rates depth (it's good at
# relative magnitude); est_windows is derived for the budget matcher/runner only — never shown.
_DEPTH_WINDOWS = {1: 0.25, 2: 0.25, 3: 0.5, 4: 0.5, 5: 1.0, 6: 1.0, 7: 2.0, 8: 2.0, 9: 3.5, 10: 3.5}


def windows_for_depth(depth: int) -> float:
    return _DEPTH_WINDOWS[max(1, min(10, int(depth)))]


def depth_for_windows(w: float) -> int:
    """Representative display depth for a legacy job that carries only est_windows."""
    if w <= 0.375:
        return 2
    if w <= 0.75:
        return 4
    if w <= 1.5:
        return 6
    if w <= 2.75:
        return 8
    return 10


@dataclass
class Job:
    id: str
    repo: str
    title: str
    type: str
    est_windows: float            # INTERNAL cost (window-units), derived from depth; not shown
    value: float                  # the scan agent's worth ranking, drives priority
    depth: int = 5                # 1-10 agent-rated cost/depth — the DISPLAYED magnitude
    rationale: str = ""
    launch: str = ""              # prompt/command to run it (Phase 1 hands this to the user)
    verify: str = ""              # per-job test-gate override (Phase 2 runner); falls back to ROE test_cmd
    status: str = "proposed"      # proposed | queued | done (Phase 2+ uses this)

    @property
    def tier(self) -> str:
        return tier_for(self.est_windows)


def parse_jobs(data, repo: str = "") -> List[Job]:
    """Build Jobs from a list of dicts. Each needs id + value + at least one cost field
    (depth, 1-10, or legacy est_windows). Fills both: depth-> est_windows (windows_for_depth),
    or legacy est_windows -> a display depth (depth_for_windows)."""
    out: List[Job] = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        if d.get("id") is None or d.get("value") is None:
            continue
        has_depth = d.get("depth") is not None
        has_win = d.get("est_windows") is not None
        if not (has_depth or has_win):
            continue
        if has_depth:
            depth = max(1, min(10, int(d["depth"])))
            est = windows_for_depth(depth)
        else:
            est = float(d["est_windows"])
            depth = depth_for_windows(est)
        out.append(Job(
            id=str(d["id"]),
            repo=d.get("repo") or repo,
            title=d.get("title", ""),
            type=d.get("type", "other"),
            est_windows=est,
            value=float(d["value"]),
            depth=depth,
            rationale=d.get("rationale", ""),
            launch=d.get("launch", ""),
            verify=d.get("verify", ""),
            status=d.get("status", "proposed"),
        ))
    return out
