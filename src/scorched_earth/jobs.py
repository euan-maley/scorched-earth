"""Job schema for the COA advisor: the expensive-work items a repo scan produces and the
priority matcher consumes. Pure, stdlib only. Jobs are rated by DEFCON criticality
(1 = most critical / project-defining, 5 = trivial) — impact on the project, never effort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


def clamp_defcon(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, n))


@dataclass
class Job:
    id: str
    repo: str
    title: str
    type: str
    defcon: int = 3               # 1..5 criticality, 1 = most critical (project impact)
    value: float = 0.0            # within-DEFCON tie-breaker (agent's worth ranking)
    rationale: str = ""
    launch: str = ""              # prompt/command to run it
    verify: str = ""              # per-job test-gate override; falls back to ROE test_cmd
    status: str = "proposed"      # proposed | queued | done


def parse_jobs(data, repo: str = "") -> List[Job]:
    """Build Jobs from a list of dicts. Each needs an `id`. `defcon` defaults to 3 when absent
    (clean-break: legacy depth/est_windows fields are ignored). `value` defaults to 0."""
    out: List[Job] = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        if d.get("id") is None:
            continue
        out.append(Job(
            id=str(d["id"]),
            repo=d.get("repo") or repo,
            title=d.get("title", ""),
            type=d.get("type", "other"),
            defcon=clamp_defcon(d.get("defcon", 3)),
            value=float(d.get("value", 0) or 0),
            rationale=d.get("rationale", ""),
            launch=d.get("launch", ""),
            verify=d.get("verify", ""),
            status=d.get("status", "proposed"),
        ))
    return out
