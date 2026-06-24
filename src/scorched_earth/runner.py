"""The COA queue-runner: drains .scorched/queue.json, executes each job headless in a
sandboxed git worktree under the ROE leash, and emits a live After-Action Report. I/O tier
(subprocess + git); never imported by the statusline hot path. The budget/planning core
(`plan_run`) is pure and unit-tested; the per-job real-world work is one injected callable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .jobs import Job
from .roe import ROE

_EPS = 1e-9

# Default unattended leash: additive / verifiable work only. A repo widens this via ROE
# unattended_types. Transformative types (refactor/fix/infra) never run unattended by default.
SAFE_UNATTENDED = ["test", "docs", "perf", "audit"]


def _allowed_unattended(roe: ROE, job_type: str) -> bool:
    allowed = roe.unattended_types if roe.unattended_types is not None else SAFE_UNATTENDED
    return job_type in allowed


def plan_run(jobs: List[Job], envelope: float, roe: ROE) -> Tuple[List[Tuple[Job, str]], float]:
    """Pure: classify each queued job's pre-run disposition without executing anything.

    Walks the queue in its existing (ranked) order. ROE-blocked jobs are skipped and consume
    no budget. The first eligible job that won't fit the envelope — and every eligible job
    after it — is skipped-budget (the queue is already best-first, so we don't backfill).
    Returns (dispositions, predicted_spend) where predicted_spend sums est_windows of every
    'run' job (the work spends budget whether or not its gate later passes).
    """
    out: List[Tuple[Job, str]] = []
    spent = 0.0
    budget_gone = False
    for j in jobs:
        if not _allowed_unattended(roe, j.type):
            out.append((j, "blocked-roe"))
            continue
        if budget_gone or spent + j.est_windows > envelope + _EPS:
            budget_gone = True
            out.append((j, "skipped-budget"))
            continue
        spent += j.est_windows
        out.append((j, "run"))
    return out, spent


@dataclass
class JobOutcome:
    seq: int
    id: str
    title: str
    type: str
    tier: str
    outcome: str                      # running|pass|fail|blocked-roe|skipped-budget|pending
    est_windows: float
    branch: Optional[str] = None
    diff: Optional[dict] = None       # {"files":int,"insertions":int,"deletions":int} or None
    note: str = ""
    merge_cmd: Optional[str] = None
    discard_cmd: Optional[str] = None


@dataclass
class RunResult:
    generated_at: str
    state: str                        # running | done
    repo: str
    verdict: str
    note: str
    available_windows: float
    spent_estimated: float
    jobs: List[JobOutcome] = field(default_factory=list)
    refresh_seconds: int = 6
    sector: str = "SECTOR 07"


def is_stale(state: Optional[dict], now: int) -> bool:
    """A run needs a recent snapshot. Stale when there's no usable snapshot, or the cached
    5-hour window has already reset (so windows_left no longer reflects reality)."""
    snap = (state or {}).get("snapshot") or {}
    if snap.get("seven_day_pct") is None:
        return True
    reset = snap.get("five_hour_reset")
    if reset is None:                 # incomplete snapshot: can't verify freshness -> stale
        return True
    return reset < now


def read_envelope(state: Optional[dict], roe: ROE, now: int) -> Optional[float]:
    """The window envelope for this run, from the cached snapshot's windows_left, capped by
    ROE max_windows. Returns None (refuse) when the snapshot is stale/missing — the same
    honesty rule `scorch --report` enforces. Staleness is delegated to is_stale (needs `now`),
    so the runner never plans against an elapsed window."""
    if is_stale(state, now):
        return None
    rec = (state or {}).get("recommendation") or {}
    wl = rec.get("windows_left")
    if wl is None:
        return None
    env = max(0.0, float(wl))
    if roe.max_windows is not None:
        env = min(env, roe.max_windows)
    return env
