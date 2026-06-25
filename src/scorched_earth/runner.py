"""The COA queue-runner: drains .scorched/queue.json, executes each job headless in a
sandboxed git worktree under the ROE leash, and emits a live After-Action Report. I/O tier
(subprocess + git); never imported by the statusline hot path. The budget/planning core
(`plan_run`) is pure and unit-tested; the per-job real-world work is one injected callable."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import coa_io
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


# ---------------------------------------------------------------------------
# Path / branch helpers
# ---------------------------------------------------------------------------

def branch_name(job_id: str) -> str:
    return "scorched/{}".format(job_id)


def worktree_path(repo: str, job_id: str) -> str:
    return os.path.join(os.path.realpath(os.path.expanduser(repo)), ".scorched", "wt", job_id)


def merge_cmd(repo: str, job_id: str) -> str:
    return "git -C {} merge {}".format(repo, branch_name(job_id))


def discard_cmd(repo: str, job_id: str) -> str:
    return (
        "git -C {repo} worktree remove --force {wt} && "
        "git -C {repo} branch -D {br}"
    ).format(repo=repo, wt=worktree_path(repo, job_id), br=branch_name(job_id))


# ---------------------------------------------------------------------------
# Sandbox settings
# ---------------------------------------------------------------------------

def write_sandbox_settings(worktree: str) -> None:
    """Write <worktree>/.claude/settings.json with Claude Code sandbox config.

    Network is restricted to api.anthropic.com only — npm/pypi are NOT allowlisted
    because the runner pre-warms deps via setup_cmd (trusted, network-enabled) BEFORE
    the sandboxed agent runs. The agent stays offline.

    Caveats:
    - Hostname-only network filtering (no TLS inspection); narrow allowlists matter. With
      API-only + offline agent this is moot.
    - Linux requires bubblewrap+socat installed for sandbox enforcement.
    - failIfUnavailable: true makes a missing sandbox a hard error rather than silently
      running unconfined — correct for an autonomous executor.
    """
    claude_dir = os.path.join(worktree, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    settings = {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "network": {
                # API-only allowlist is what actually prevents push/exfil: the prelude's
                # "DO NOT push" is advisory. Loosening allowedDomains (e.g. to add a package
                # registry) is a SECURITY CHANGE that could open a push or exfiltration path.
                "allowedDomains": ["api.anthropic.com", "*.anthropic.com"],
            },
            "filesystem": {
                "denyRead": ["~/.ssh", "~/.aws"],
            },
        }
    }
    with open(os.path.join(claude_dir, "settings.json"), "w") as fh:
        json.dump(settings, fh, indent=2)


# ---------------------------------------------------------------------------
# Claude command builder
# ---------------------------------------------------------------------------

_PRELUDE = (
    "You are running UNATTENDED inside an isolated git worktree. Operating orders: "
    "work ONLY in this worktree; make additive, focused changes; when done, commit with a "
    "clear message. DO NOT push. DO NOT touch other repositories or files outside the worktree. "
    "Task follows.\n\n"
)


def build_claude_cmd(job: "Job", worktree: str) -> List[str]:
    """Headless, sandboxed claude invocation.

    Containment is achieved via two orthogonal mechanisms:
      1. cwd=worktree scopes filesystem writes to the worktree.
      2. write_sandbox_settings() writes <worktree>/.claude/settings.json before the
         spawn, enforcing OS-level sandbox (Seatbelt on macOS, bubblewrap+socat on Linux)
         with API-only network and credential-dir denyRead.

    --dangerously-skip-permissions suppresses interactive prompts. Does NOT work as root.
    --add-dir is intentionally omitted: sandbox settings + cwd handle containment.
    """
    return [
        "claude", "-p", _PRELUDE + (job.launch or job.title),
        "--dangerously-skip-permissions",
    ]


def build_gate_cmd(job: "Job", roe: "ROE") -> Optional[str]:
    return job.verify or roe.test_cmd or None


# ---------------------------------------------------------------------------
# Internal git helpers
# ---------------------------------------------------------------------------

def _git(repo_root: str, *args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(["git", "-C", repo_root] + list(args),
                          capture_output=True, text=True)


def _diffstat(worktree: str, base_sha: str) -> Optional[dict]:
    p = _git(worktree, "diff", "--numstat", base_sha + "..HEAD")
    if p.returncode != 0 or not p.stdout.strip():
        return None
    files = ins = dele = 0
    for line in p.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            ins += int(parts[0])
            dele += int(parts[1])
            files += 1
    return {"files": files, "insertions": ins, "deletions": dele}


# ---------------------------------------------------------------------------
# Killable executor primitive (Phase 2c)
# ---------------------------------------------------------------------------

# Ambient handle to the currently-running job's kill Event, set by the cockpit Engine on the
# same worker thread execute_job runs on (so no execute/run_one signature change). None in the
# batch `scorch coa run` path.
_kill_ctx = threading.local()


def _run_killable(cmd, cwd, kill_event, grace=3.0, poll=0.1):
    """Run cmd; if kill_event is set, terminate (SIGTERM, then SIGKILL after `grace`) and return
    'killed'. Returns 'done' when the process exits on its own (or kill_event is None)."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if kill_event is None:
        p.wait()
        return "done"
    while p.poll() is None:
        if kill_event.is_set():
            p.terminate()
            try:
                p.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            return "killed"
        time.sleep(poll)
    return "done"


def _discard_worktree(root, job_id):
    """Always-discard: drop a killed job's worktree + branch (no keep option)."""
    _git(root, "worktree", "remove", "--force", worktree_path(root, job_id))
    _git(root, "branch", "-D", branch_name(job_id))


# ---------------------------------------------------------------------------
# execute_job — real per-job work
# ---------------------------------------------------------------------------

def execute_job(repo: str, job: "Job", roe: "ROE") -> Tuple[str, Optional[dict], str]:
    """Real per-job work: worktree -> sandbox settings -> pre-warm deps -> sandboxed
    claude -p -> test gate.

    Returns (outcome, diff, note). Outcome is 'pass' or 'fail'. The orchestration in
    run_queue treats any exception here as a 'fail' so one bad job never aborts the run.

    Sandbox caveats (from planning lookup):
    - Network filtering is hostname-only (no TLS inspection); narrow allowlists matter.
      With API-only + offline agent this is moot for our use case.
    - Linux needs bubblewrap+socat installed; failIfUnavailable: true makes a missing
      sandbox a hard error rather than silently running unconfined — correct for an
      autonomous executor.
    """
    root = os.path.realpath(os.path.expanduser(repo))
    wt = worktree_path(repo, job.id)
    br = branch_name(job.id)
    try:
        base = _git(root, "rev-parse", "HEAD")
        base_sha = base.stdout.strip() if base.returncode == 0 else "HEAD~1"
        # Worktree add is INSIDE the try AND its return code is checked: _git never raises
        # (no check=True), so a failed add (dup branch, full disk) must not silently proceed
        # against a missing worktree, nor abort the whole run.
        wadd = _git(root, "worktree", "add", "-b", br, wt, "HEAD")
        if wadd.returncode != 0:
            return "fail", None, "worktree add failed: " + (wadd.stderr or "").strip()[:200]
        # Write sandbox settings BEFORE any spawn so the agent starts confined.
        write_sandbox_settings(wt)
        if roe.setup_cmd:           # pre-warm deps with network (trusted, runner-run)
            subprocess.run(roe.setup_cmd, cwd=wt, shell=True,
                           capture_output=True, text=True)
        # Killable claude step: the cockpit Engine may set _kill_ctx.event for this job.
        if _run_killable(build_claude_cmd(job, wt), wt,
                         getattr(_kill_ctx, "event", None)) == "killed":
            _discard_worktree(root, job.id)        # always discard the partial work
            return "killed", None, "killed by operator — work discarded."
        diff = _diffstat(wt, base_sha)
        gate = build_gate_cmd(job, roe)
        if gate is None:
            return "pass", diff, "no gate configured (ROE test_cmd unset) — review manually."
        g = subprocess.run(gate, cwd=wt, shell=True, capture_output=True, text=True)
        if g.returncode == 0:
            return "pass", diff, "gate passed."
        return "fail", diff, "gate FAILED ({}) — branch kept for triage.".format(gate)
    except Exception as e:          # noqa: BLE001 — never let one job abort the run
        return "fail", None, "runner error: {}".format(e)


def _outcome_for(job: Job, seq: int, disposition: str) -> JobOutcome:
    note = {"blocked-roe": f"type '{job.type}' not in unattended leash — not run.",
            "skipped-budget": "no budget left when reached."}[disposition]
    return JobOutcome(seq=seq, id=job.id, title=job.title, type=job.type, tier=job.tier,
                      outcome=disposition, est_windows=job.est_windows, note=note)


def run_one(repo, job, roe, repo_disp, seq, *, execute, on_running=None):
    """Execute one job and return its finished JobOutcome. Builds the 'running' outcome,
    optionally surfaces it via on_running (live two-phase), runs the injected `execute`
    (any raise -> 'fail' so one job never aborts a run), then fills the result. No I/O of
    its own — the caller persists. Shared by the batch run_queue and the cockpit engine."""
    oc = JobOutcome(seq=seq, id=job.id, title=job.title, type=job.type, tier=job.tier,
                    outcome="running", est_windows=job.est_windows, branch=branch_name(job.id))
    if on_running:
        on_running(oc)
    try:
        outcome, diff, note = execute(repo, job, roe)
    except Exception as e:                  # noqa: BLE001 — never let one job abort the run
        outcome, diff, note = "fail", None, "runner error: {}".format(e)
    oc.outcome, oc.diff, oc.note = outcome, diff, note
    oc.merge_cmd = merge_cmd(repo_disp, job.id)
    oc.discard_cmd = discard_cmd(repo_disp, job.id)
    return oc


def run_queue(repo, state, *, now, date, execute=None, on_step=None):
    """Drain the queue under the full safety model. Returns the final RunResult, or None if it
    refuses (stale/absent snapshot). Persists the record + HTML after every job so the same
    artifact is the live monitor and the final debrief. `execute` is injected for testing."""
    from . import review_report as _rev   # lazy: avoid import cycle at module load
    execute = execute or execute_job

    roe = coa_io.load_roe(repo)
    envelope = read_envelope(state, roe, now)
    if envelope is None:
        return None

    queue = coa_io.read_queue(repo)
    dispositions, predicted = plan_run(queue, envelope, roe)
    verdict = ((state or {}).get("recommendation") or {}).get("level", "unknown")
    repo_disp = os.path.realpath(os.path.expanduser(repo))

    rr = RunResult(generated_at=date, state="running", repo=repo_disp, verdict=verdict,
                   note="", available_windows=envelope, spent_estimated=0.0)

    def _persist():
        rr.note = _summary(rr)
        coa_io.write_run_record(repo, _dataclass_dict(rr), date)
        html = _rev.render_review_html(rr)
        with open(os.path.join(coa_io.runs_dir(repo), f"{date}.html"), "w") as f:
            f.write(html)
        if on_step:
            on_step(rr)

    spent = 0.0
    for i, (job, disp) in enumerate(dispositions, start=1):
        if disp != "run":
            rr.jobs.append(_outcome_for(job, i, disp))
            _persist()
            continue
        oc = run_one(repo, job, roe, repo_disp, i, execute=execute,
                     on_running=lambda r: (rr.jobs.append(r), _persist()))
        rr.jobs[-1] = oc                      # replace the 'running' outcome with the finished one
        spent += job.est_windows
        rr.spent_estimated = spent
        _persist()

    rr.state = "done"
    _persist()
    return rr


def _summary(rr: RunResult) -> str:
    n = {}
    for j in rr.jobs:
        n[j.outcome] = n.get(j.outcome, 0) + 1
    parts = []
    if n.get("pass"):           parts.append(f"{n['pass']} secured")
    if n.get("fail"):           parts.append(f"{n['fail']} cratered")
    if n.get("blocked-roe"):    parts.append(f"{n['blocked-roe']} blocked")
    if n.get("skipped-budget"): parts.append(f"{n['skipped-budget']} forfeit")
    if n.get("running"):        parts.append(f"{n['running']} working")
    head = ", ".join(parts) if parts else "no jobs"
    return f"{head}. ~{rr.spent_estimated:.1f} of {rr.available_windows:.1f} windows (estimated)."


def _dataclass_dict(rr: RunResult) -> dict:
    from dataclasses import asdict
    return asdict(rr)


def pick_next(queue, available, roe):
    """First queued job that is ROE-allowed and fits `available` (window-units). Skips
    ahead past a too-big or ROE-blocked card — the interactive cockpit runs what fits
    rather than stalling the whole queue on the top card. None if nothing is eligible."""
    for j in queue:
        if not _allowed_unattended(roe, j.type):
            continue
        if j.est_windows <= available + _EPS:
            return j
    return None


class EnvelopeTracker:
    """Refreshing budget envelope for the cockpit. Predicts spend between snapshots and
    re-syncs to ground truth whenever an interactive session advances state.json's snapshot
    timestamp (the new windows_left already reflects the engine's real headless burn)."""

    def __init__(self, roe):
        self.roe = roe
        self._synced_ts = object()      # sentinel: forces a re-sync on first call
        self.spent = 0.0

    def available(self, state, now):
        snap = (state or {}).get("snapshot") or {}
        ts = snap.get("now")
        if ts != self._synced_ts:       # snapshot advanced -> re-sync to ground truth
            self._synced_ts = ts
            self.spent = 0.0
        base = read_envelope(state, self.roe, now)
        if base is None:
            return None
        return max(0.0, base - self.spent)

    def charge(self, est):
        self.spent += est
