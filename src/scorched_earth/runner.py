"""The COA queue-runner: drains .scorched/queue.json in DEFCON order, executes each job headless
in a sandboxed git worktree under the ROE leash, and emits a live After-Action Report. I/O tier
(subprocess + git); never imported by the statusline hot path. The pre-run disposition core
(`plan_run`) is pure and unit-tested; the per-job real-world work is one injected callable. There
is no budget layer — execution stops on the real usage-limit, not a predicted envelope."""

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

# Default unattended leash: additive / verifiable work only. A repo widens this via ROE
# unattended_types. Transformative types (refactor/fix/infra) never run unattended by default.
SAFE_UNATTENDED = ["test", "docs", "perf", "audit"]


def _allowed_unattended(roe: ROE, job_type: str) -> bool:
    allowed = roe.unattended_types if roe.unattended_types is not None else SAFE_UNATTENDED
    return job_type in allowed


def plan_run(jobs: List[Job], roe: ROE, *, approved: bool = False) -> List[Tuple[Job, str]]:
    """Pure pre-run disposition: 'blocked-roe' (type not unattended), 'blocked-approval'
    (defcon below the gate and not approved), else 'run'. No budget — execution stops on a
    real usage-limit, not a predicted envelope."""
    from .advisor import approval_required
    out: List[Tuple[Job, str]] = []
    for j in jobs:
        if not _allowed_unattended(roe, j.type):
            out.append((j, "blocked-roe"))
        elif approval_required(j, roe) and not approved:
            out.append((j, "blocked-approval"))
        else:
            out.append((j, "run"))
    return out


@dataclass
class JobOutcome:
    seq: int
    id: str
    title: str
    type: str
    outcome: str                      # running|pass|fail|blocked-roe|blocked-approval|killed|limit
    defcon: int = 3                   # 1..5 criticality (mirrors Job.defcon)
    branch: Optional[str] = None
    diff: Optional[dict] = None       # {"files":int,"insertions":int,"deletions":int} or None
    note: str = ""
    merge_cmd: Optional[str] = None
    discard_cmd: Optional[str] = None


@dataclass
class RunResult:
    generated_at: str
    state: str                        # running | done | halted
    repo: str
    verdict: str
    note: str
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


def detect_rate_limit(output):
    """True when headless `claude -p --output-format stream-json` output carries the rate-limit
    signal (429 api_retry). Substring match on the stable error value; exit code alone can't tell
    a usage-limit from a normal failure. Conservative: only the rate_limit value, not 'overloaded'."""
    s = output or ""
    return '"error":"rate_limit"' in s or '"error": "rate_limit"' in s or '"rate_limit_error"' in s


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

def sandbox_settings_dict() -> dict:
    """The Claude Code OS-sandbox config, as a settings dict.

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
    return {
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


def write_sandbox_settings(worktree: str) -> None:
    """Write <worktree>/.claude/settings.json with the OS-sandbox config (headless mode).
    Attended takeover delivers the same dict via a CLI --settings file instead (see exec_modes)."""
    claude_dir = os.path.join(worktree, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    with open(os.path.join(claude_dir, "settings.json"), "w") as fh:
        json.dump(sandbox_settings_dict(), fh, indent=2)


# ---------------------------------------------------------------------------
# Claude command builder
# ---------------------------------------------------------------------------

_PRELUDE = (
    "You are running UNATTENDED inside an isolated git worktree. Operating orders: "
    "work ONLY in this worktree; make additive, focused changes; when done, commit with a "
    "clear message. DO NOT push. DO NOT touch other repositories or files outside the worktree. "
    "Task follows.\n\n"
)


# Model aliases the CLI accepts directly (verified against `claude --help`); a full "claude-*"
# id is also accepted verbatim. Anything else is ignored (inherit the session default) rather
# than passed through, so a bad scan value can never wedge the invocation.
MODEL_ALIASES = ("fable", "sonnet", "opus", "haiku")


def model_arg(job: "Job") -> List[str]:
    """['--model', <value>] when the job names a model the CLI accepts, else [] (inherit)."""
    m = (getattr(job, "model", "") or "").strip()
    if m in MODEL_ALIASES or m.startswith("claude-"):
        return ["--model", m]
    return []


def build_claude_cmd(job: "Job", worktree: str) -> List[str]:
    """Headless, sandboxed claude invocation.

    Containment is achieved via two orthogonal mechanisms:
      1. cwd=worktree scopes filesystem writes to the worktree.
      2. write_sandbox_settings() writes <worktree>/.claude/settings.json before the
         spawn, enforcing OS-level sandbox (Seatbelt on macOS, bubblewrap+socat on Linux)
         with API-only network and credential-dir denyRead.

    --dangerously-skip-permissions suppresses interactive prompts. Does NOT work as root.
    --add-dir is intentionally omitted: sandbox settings + cwd handle containment.
    --model is appended only when the job names one (per-task model selection).
    """
    return [
        "claude", "-p", _PRELUDE + (job.launch or job.title),
        "--output-format", "stream-json", "--verbose",
        "--dangerously-skip-permissions",
    ] + model_arg(job)


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
    """Run cmd capturing stdout (for rate-limit detection). Returns (status, output, returncode)
    where status is 'killed' or 'done'. Honors kill_event (SIGTERM then SIGKILL after grace).

    The command streams continuous JSON (`claude -p --output-format stream-json --verbose`). A
    DAEMON READER THREAD drains p.stdout to EOF concurrently so the child never blocks on a full
    OS pipe buffer (~64KB) while the main loop only polls poll()/kill_event. Without this drain a
    long run deadlocks: the child blocks on write(), poll() stays None forever, the worker hangs."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if kill_event is None:
        out, _ = p.communicate()        # communicate() already drains both pipes
        return "done", out or "", p.returncode
    chunks = []

    def _drain():
        try:
            for line in p.stdout:       # reads to EOF; keeps the pipe empty so the child never blocks
                chunks.append(line)
        except Exception:  # noqa: BLE001 — reader is best-effort; status/returncode still authoritative
            pass

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    while p.poll() is None:
        if kill_event.is_set():
            p.terminate()
            try:
                p.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait()
            reader.join(timeout=grace)
            return "killed", "".join(chunks), p.returncode
        time.sleep(poll)
    reader.join(timeout=grace)          # let the reader finish draining the now-closed pipe
    return ("killed" if kill_event.is_set() else "done"), "".join(chunks), p.returncode


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
        status, out, rc = _run_killable(build_claude_cmd(job, wt), wt, getattr(_kill_ctx, "event", None))
        if status == "killed":
            _discard_worktree(root, job.id)
            return "killed", None, "killed by operator — work discarded."
        if detect_rate_limit(out):
            _discard_worktree(root, job.id)             # nothing landed; job returns to the queue
            return "limit", None, "stopped: usage limit reached — re-queued, resume after reset."
        diff = _diffstat(wt, base_sha)
        # A nonzero claude exit with no changes is a real failure (e.g. a rejected flag / version
        # mismatch), not a phantom 'pass' — catch it before the gate, which would otherwise let an
        # empty no-gate run report 'pass'.
        if rc != 0 and not diff:
            return ("fail", diff,
                    "claude exited {} with no changes — flag/version error? "
                    "(check the invocation)".format(rc))
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
    if disposition == "blocked-roe":
        note = f"type '{job.type}' not in unattended leash — not run."
    elif disposition == "blocked-approval":
        note = f"DEFCON {job.defcon} needs approval — not run unattended."
    else:
        note = ""
    return JobOutcome(seq=seq, id=job.id, title=job.title, type=job.type, defcon=job.defcon,
                      outcome=disposition, note=note)


def run_one(repo, job, roe, repo_disp, seq, *, execute, on_running=None):
    """Execute one job and return its finished JobOutcome. Builds the 'running' outcome,
    optionally surfaces it via on_running (live two-phase), runs the injected `execute`
    (any raise -> 'fail' so one job never aborts a run), then fills the result. No I/O of
    its own — the caller persists. Shared by the batch run_queue and the cockpit engine."""
    oc = JobOutcome(seq=seq, id=job.id, title=job.title, type=job.type, defcon=job.defcon,
                    outcome="running", branch=branch_name(job.id))
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


def run_queue(repo, state, *, now, date, execute=None, on_step=None, approved=False):
    """Drain the queue in DEFCON order under the ROE + approval leash. Returns the final
    RunResult, or None if it refuses (stale/absent snapshot). Persists the record + HTML after
    every job so the same artifact is the live monitor and the final debrief. No budget gate:
    execution halts only on a real usage-limit. `execute` is injected for testing; `approved`
    lets gated (high-DEFCON-criticality) jobs run."""
    from . import review_report as _rev   # lazy: avoid import cycle at module load
    execute = execute or execute_job
    if is_stale(state, now):
        return None
    roe = coa_io.load_roe(repo)
    queue = coa_io.read_queue(repo)
    dispositions = plan_run(queue, roe, approved=approved)
    verdict = ((state or {}).get("recommendation") or {}).get("level", "unknown")
    repo_disp = os.path.realpath(os.path.expanduser(repo))
    rr = RunResult(generated_at=date, state="running", repo=repo_disp, verdict=verdict, note="")

    def _persist():
        rr.note = _summary(rr)
        coa_io.write_run_record(repo, _dataclass_dict(rr), date)
        html = _rev.render_review_html(rr)
        with open(os.path.join(coa_io.runs_dir(repo), f"{date}.html"), "w") as f:
            f.write(html)
        if on_step:
            on_step(rr)

    for i, (job, disp) in enumerate(dispositions, start=1):
        if disp != "run":
            rr.jobs.append(_outcome_for(job, i, disp))
            _persist()
            continue
        oc = run_one(repo, job, roe, repo_disp, i, execute=execute,
                     on_running=lambda r: (rr.jobs.append(r), _persist()))
        rr.jobs[-1] = oc                      # replace the 'running' outcome with the finished one
        if oc.outcome == "limit":
            rr.state = "halted"
            _persist()
            return rr
        _persist()
    rr.state = "done"
    _persist()
    return rr


def _summary(rr: RunResult) -> str:
    n = {}
    for j in rr.jobs:
        n[j.outcome] = n.get(j.outcome, 0) + 1
    parts = []
    if n.get("pass"):              parts.append(f"{n['pass']} secured")
    if n.get("fail"):              parts.append(f"{n['fail']} cratered")
    if n.get("blocked-roe"):       parts.append(f"{n['blocked-roe']} blocked (ROE)")
    if n.get("blocked-approval"):  parts.append(f"{n['blocked-approval']} need approval")
    if n.get("killed"):            parts.append(f"{n['killed']} killed")
    if n.get("running"):           parts.append(f"{n['running']} working")
    return (", ".join(parts) if parts else "no jobs") + "."


def _dataclass_dict(rr: RunResult) -> dict:
    from dataclasses import asdict
    return asdict(rr)


def pick_next(queue, roe, *, approved=False):
    """First queued job ROE-allowed to run unattended and not gated behind approval (unless
    approved). Drains in given order; the queue is already DEFCON-sorted by the matcher."""
    from .advisor import approval_required
    for j in queue:
        if _allowed_unattended(roe, j.type) and (approved or not approval_required(j, roe)):
            return j
    return None
