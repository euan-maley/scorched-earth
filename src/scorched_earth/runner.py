"""The COA queue-runner: drains .scorched/queue.json in DEFCON order, executes each job headless
in a sandboxed git worktree under the ROE leash, and emits a live After-Action Report. I/O tier
(subprocess + git); never imported by the statusline hot path. The pre-run disposition core
(`plan_run`) is pure and unit-tested; the per-job real-world work is one injected callable. There
is no budget layer — execution stops on the real usage-limit, not a predicted envelope."""

from __future__ import annotations

import json
import os
import shlex
import signal
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
    outcome: str                      # running|pass|fail|blocked-roe|blocked-approval|killed|limit|roadblocked
    defcon: int = 3                   # 1..5 criticality (mirrors Job.defcon)
    branch: Optional[str] = None
    diff: Optional[dict] = None       # {"files":int,"insertions":int,"deletions":int} or None
    note: str = ""
    merge_cmd: Optional[str] = None
    discard_cmd: Optional[str] = None
    deliverable: Optional[str] = None  # repo-relative path to the per-job deliverable record
    roadblock: Optional[str] = None    # repo-relative path to the roadblock report (roadblocked only)


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


def summarize_stream_line(line):
    """Best-effort one-line human summary of a `claude --output-format stream-json` line, for the
    live progress view: the latest tool call or assistant text. Falls back to a trimmed raw line.
    Pure, tolerant of anything non-JSON."""
    s = (line or "").strip()
    if not s:
        return ""
    try:
        obj = json.loads(s)
    except Exception:  # noqa: BLE001 — non-JSON chatter: show a trimmed raw line
        return s[:200]
    msg = obj.get("message") if isinstance(obj, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                inp = block.get("input") or {}
                hint = (inp.get("command") or inp.get("file_path") or inp.get("path")
                        or inp.get("pattern") or "")
                return "tool: {} {}".format(block.get("name", "tool"), hint).strip()[:200]
            if block.get("type") == "text":
                txt = (block.get("text") or "").strip().replace("\n", " ")
                if txt:
                    return txt[:200]
    # A parsed JSON object with no extractable tool_use/text hint is structural-only chatter
    # (e.g. a bare "assistant"/"user" message wrapper). Returning "" lets the caller keep the
    # previous line on screen instead of flashing a meaningless "[assistant]"/"[user]" marker
    # onto the live CRT feed.
    if isinstance(obj, dict):
        return ""
    return s[:200]


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
    return "git -C {} merge {}".format(shlex.quote(repo), shlex.quote(branch_name(job_id)))


def discard_cmd(repo: str, job_id: str) -> str:
    return (
        "git -C {repo} worktree remove --force {wt} && "
        "git -C {repo} branch -D {br}"
    ).format(repo=shlex.quote(repo), wt=shlex.quote(worktree_path(repo, job_id)),
             br=shlex.quote(branch_name(job_id)))


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


_ADVISOR_PRELUDE = (
    "You are a RECOVERY agent. A prior unattended run in THIS worktree hit a roadblock and could "
    "not finish. Diagnose the problem below, apply a focused, additive fix so the original task "
    "can complete, and make the verification gate pass. Work ONLY in this worktree; commit when "
    "done; DO NOT push. The roadblock:\n\n"
)


def build_advisor_cmd(job: "Job", roe: "ROE", problem: str) -> List[str]:
    """Headless, sandboxed claude invocation for one bounded recovery attempt on a roadblocked
    job. Same containment as build_claude_cmd; the prompt is the roadblock + the original task."""
    prompt = _ADVISOR_PRELUDE + problem + "\n\nOriginal task:\n" + (job.launch or job.title)
    return [
        "claude", "-p", prompt,
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
        if len(parts) < 2:
            continue
        if parts[0].isdigit() and parts[1].isdigit():
            ins += int(parts[0])
            dele += int(parts[1])
            files += 1
        elif parts[0] == "-" and parts[1] == "-":
            # binary file: git reports "-\t-\tpath" (no line counts) instead of numbers.
            # Still count it as a changed file so a binary-only change isn't reported as None.
            files += 1
    return {"files": files, "insertions": ins, "deletions": dele}


# ---------------------------------------------------------------------------
# Killable executor primitive (Phase 2c)
# ---------------------------------------------------------------------------

# Ambient handle to the currently-running job's kill Event, set by the cockpit Engine on the
# same worker thread execute_job runs on (so no execute/run_one signature change). None in the
# batch `scorch coa run` path.
_kill_ctx = threading.local()


def _signal_group(p, sig):
    """Send sig to p's whole process group (catches grandchildren a plain p.terminate()/p.kill()
    would leave running, e.g. a shell launching claude). Falls back to the direct-child signal
    when the group lookup fails (already dead, no permission, or start_new_session wasn't used)."""
    try:
        os.killpg(os.getpgid(p.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        (p.terminate if sig == signal.SIGTERM else p.kill)()


def _terminate(p, grace):
    """SIGTERM then SIGKILL after grace, to the whole process group."""
    _signal_group(p, signal.SIGTERM)
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        _signal_group(p, signal.SIGKILL)
        p.wait()


def _run_killable(cmd, cwd, kill_event, grace=3.0, poll=0.1, idle_secs=None, on_line=None):
    """Run cmd capturing stdout (for rate-limit detection). Returns (status, output, returncode)
    where status is 'killed', 'idle' (no output for idle_secs = stuck = a roadblock), or 'done'.
    Honors kill_event (SIGTERM then SIGKILL after grace). on_line, if given, is called with each
    output line (for the live progress view).

    The command streams continuous JSON (`claude -p --output-format stream-json --verbose`). A
    DAEMON READER THREAD drains p.stdout to EOF concurrently so the child never blocks on a full
    OS pipe buffer (~64KB) while the main loop only polls poll()/kill_event. Without this drain a
    long run deadlocks: the child blocks on write(), poll() stays None forever, the worker hangs.
    The reader also stamps the last-output time so the idle watchdog can spot a stuck job."""
    # start_new_session=True puts the child in its own process group, so _terminate can signal
    # the whole group (e.g. a shell + its claude grandchild) instead of just the direct child,
    # which would otherwise survive SIGTERM/SIGKILL and keep running after a "killed" outcome.
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         start_new_session=True)
    if kill_event is None and idle_secs is None and on_line is None:
        out, _ = p.communicate()        # fast path: no kill/idle/progress watch -> communicate()
        return "done", out or "", p.returncode
    chunks = []
    last = [time.time()]                 # time of the most recent output line (idle watchdog)

    def _drain():
        try:
            for line in p.stdout:       # reads to EOF; keeps the pipe empty so the child never blocks
                chunks.append(line)
                last[0] = time.time()
                if on_line:
                    try:
                        on_line(line)
                    except Exception:  # noqa: BLE001 — progress sink is best-effort
                        pass
        except Exception:  # noqa: BLE001 — reader is best-effort; status/returncode still authoritative
            pass

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    while p.poll() is None:
        if kill_event is not None and kill_event.is_set():
            _terminate(p, grace)
            reader.join(timeout=grace)
            return "killed", "".join(chunks), p.returncode
        if idle_secs is not None and (time.time() - last[0]) > idle_secs:
            _terminate(p, grace)
            reader.join(timeout=grace)
            return "idle", "".join(chunks), p.returncode
        time.sleep(poll)
    reader.join(timeout=grace)          # let the reader finish draining the now-closed pipe
    return ("killed" if (kill_event is not None and kill_event.is_set()) else "done"), \
        "".join(chunks), p.returncode


def _discard_worktree(root, job_id):
    """Always-discard: drop a killed job's worktree + branch (no keep option)."""
    _git(root, "worktree", "remove", "--force", worktree_path(root, job_id))
    _git(root, "branch", "-D", branch_name(job_id))


# ---------------------------------------------------------------------------
# Roadblock recovery: one bounded advising-agent attempt, then re-gate
# ---------------------------------------------------------------------------

def _try_advise(wt, job, roe, base_sha, problem):
    """One bounded recovery attempt: run an advising agent in the worktree, then re-gate.
    Returns (verdict, diff, note); verdict is 'solved' | 'unsolved' | 'killed' | 'limit'.
    Solved only when a gate exists and passes after the fix. A kill or usage-limit during
    the attempt is surfaced as its own verdict so the caller can escalate (a limit must
    halt the whole run, not mislabel the job roadblocked and spawn the next job into it)."""
    status, out, rc = _run_killable(build_advisor_cmd(job, roe, problem), wt,
                                    getattr(_kill_ctx, "event", None),
                                    idle_secs=(roe.roadblock_idle_secs or None),
                                    on_line=getattr(_kill_ctx, "progress", None))
    diff = _diffstat(wt, base_sha)
    if status == "killed":
        return "killed", diff, "killed by operator during recovery."
    if detect_rate_limit(out):
        return "limit", diff, "usage limit hit during recovery."
    if status == "idle":
        return "unsolved", diff, "advising agent could not recover (idle)."
    gate = build_gate_cmd(job, roe)
    if gate is None:
        return "unsolved", diff, "advising agent ran but there is no gate to confirm recovery."
    gstatus, gout, grc = _run_killable(["/bin/sh", "-c", gate], wt,
                                       getattr(_kill_ctx, "event", None))
    if gstatus == "killed":
        return "killed", diff, "killed by operator during recovery."
    if grc == 0:
        return "solved", diff, "gate passed after recovery."
    return "unsolved", diff, "advising agent's fix still fails the gate."


def _roadblock_or_advise(wt, job, roe, base_sha, reason):
    """Turn a detected roadblock into an outcome: if advise_on_roadblock, try one recovery
    attempt (a pass on success), else record 'roadblocked' with a resume hint. A kill or
    usage-limit during the attempt escalates as its own outcome (execute_job maps 'killed'
    to a discard and 'limit' to a run halt)."""
    advised = ""
    if roe.advise_on_roadblock:
        verdict, diff, note = _try_advise(wt, job, roe, base_sha, reason)
        if verdict == "solved":
            return "pass", diff, "roadblock auto-solved by advising agent ({}). {}".format(reason, note)
        if verdict in ("killed", "limit"):
            return verdict, diff, note
        advised = " (advising agent could not recover)"
    else:
        diff = _diffstat(wt, base_sha)
    return ("roadblocked", diff,
            "roadblock: {}.{} Branch kept; `scorch coa resume {}`.".format(reason, advised, job.id))


def _map_recovery(root, job, br, oc):
    """Map a recovery-phase escalation to its run-level outcome: an operator kill discards the
    work (kill means 'get rid of it'); a usage limit keeps the branch (the job stays queued and
    auto-resumes after the reset). Everything else passes through."""
    outcome, diff, note = oc
    if outcome == "killed":
        _discard_worktree(root, job.id)
        return "killed", None, "killed by operator, work discarded."
    if outcome == "limit":
        return "limit", diff, ("stopped: usage limit during recovery; work kept on {}, "
                               "auto-resumes on the next run after reset.".format(br))
    return outcome, diff, note


# ---------------------------------------------------------------------------
# execute_job — real per-job work
# ---------------------------------------------------------------------------

def execute_job(repo: str, job: "Job", roe: "ROE", *, resume: bool = False) -> Tuple[str, Optional[dict], str]:
    """Real per-job work: worktree -> sandbox settings -> pre-warm deps -> sandboxed
    claude -p -> test gate.

    Returns (outcome, diff, note). Outcome is one of pass | fail | killed | limit | roadblocked.
    A ROADBLOCK (stuck past the ROE idle timeout, or a failed gate) KEEPS the branch so the
    advising agent / operator can pick it up and `scorch coa resume <id>` can continue. The
    orchestration in run_queue treats any exception here as a 'fail' so one bad job never aborts
    the run. resume=True reuses an existing worktree/branch from a prior roadblocked attempt
    instead of creating a fresh one.

    Sandbox caveats (from planning lookup):
    - Network filtering is hostname-only (no TLS inspection); narrow allowlists matter.
      With API-only + offline agent this is moot for our use case.
    - Linux needs bubblewrap+socat installed; failIfUnavailable: true makes a missing
      sandbox a hard error rather than silently running unconfined, correct for an
      autonomous executor.
    """
    root = os.path.realpath(os.path.expanduser(repo))
    wt = worktree_path(repo, job.id)
    br = branch_name(job.id)
    try:
        base = _git(root, "rev-parse", "HEAD")
        base_sha = base.stdout.strip() if base.returncode == 0 else "HEAD~1"
        br_exists = _git(root, "rev-parse", "--verify", "--quiet", br).returncode == 0
        if not resume and br_exists:
            # A prior attempt KEPT work here (a roadblock report, or commits HEAD doesn't
            # have, e.g. a mid-job usage limit). A plain re-dispatch must continue it, not
            # silently destroy it: auto-switch to resume.
            ahead = _git(root, "rev-list", "--count", "HEAD.." + br).stdout.strip()
            if ahead not in ("", "0") or os.path.exists(coa_io.roadblock_path(repo, job.id)):
                resume = True
        if resume:
            # Continue a prior kept attempt. Its worktree may have been pruned (a limit halt
            # keeps only the branch); recreate it from the kept branch in that case.
            if not os.path.isdir(wt):
                if not br_exists:
                    return "fail", None, "resume: no prior worktree at {} (nothing to continue).".format(wt)
                wadd = _git(root, "worktree", "add", wt, br)
                if wadd.returncode != 0:
                    return "fail", None, "resume: worktree re-add failed: " + (wadd.stderr or "").strip()[:200]
        else:
            # A leftover worktree/branch with nothing kept (no report, no commits ahead) is a
            # dead remnant of an interrupted run; clear the stale pair so the re-run starts
            # clean instead of cratering on "branch already exists".
            if os.path.isdir(wt) or br_exists:
                _discard_worktree(root, job.id)
            # Worktree add is INSIDE the try AND its return code is checked: _git never raises
            # (no check=True), so a failed add (full disk, etc.) must not silently proceed against
            # a missing worktree, nor abort the whole run.
            wadd = _git(root, "worktree", "add", "-b", br, wt, "HEAD")
            if wadd.returncode != 0:
                return "fail", None, "worktree add failed: " + (wadd.stderr or "").strip()[:200]
        # Write sandbox settings BEFORE any spawn so the agent starts confined.
        write_sandbox_settings(wt)
        if roe.setup_cmd:           # pre-warm deps with network (trusted, runner-run)
            sstatus, _sout, _src = _run_killable(["/bin/sh", "-c", roe.setup_cmd], wt,
                                                 getattr(_kill_ctx, "event", None))
            if sstatus == "killed":
                _discard_worktree(root, job.id)
                return "killed", None, "killed by operator, work discarded."
        # Killable claude step: the cockpit Engine may set _kill_ctx.event for this job. The idle
        # watchdog flags a job that has gone silent past the ROE timeout as a roadblock.
        status, out, rc = _run_killable(build_claude_cmd(job, wt), wt,
                                        getattr(_kill_ctx, "event", None),
                                        idle_secs=(roe.roadblock_idle_secs or None),
                                        on_line=getattr(_kill_ctx, "progress", None))
        if status == "killed":
            _discard_worktree(root, job.id)
            return "killed", None, "killed by operator, work discarded."
        if status == "idle":                            # stuck: try recovery, else keep for resume
            secs = int(roe.roadblock_idle_secs or 0)
            dur = "{}m".format(secs // 60) if secs >= 60 else "{}s".format(secs)
            return _map_recovery(root, job, br,
                                 _roadblock_or_advise(wt, job, roe, base_sha,
                                                      "no output for {} (stuck)".format(dur)))
        if detect_rate_limit(out):
            diff = _diffstat(wt, base_sha)
            if resume or diff:
                # Committed work exists on the branch (a resumed attempt, or partial commits
                # before the ceiling hit): keep it. The job stays queued and the kept-work
                # guard above auto-resumes it on the next run after the reset.
                return "limit", diff, ("stopped: usage limit reached; work so far kept on {}, "
                                       "auto-resumes on the next run after reset.".format(br))
            _discard_worktree(root, job.id)             # nothing landed; job stays queued
            return "limit", None, ("stopped: usage limit reached, nothing landed; "
                                   "job stays queued, run again after reset.")
        diff = _diffstat(wt, base_sha)
        # A nonzero claude exit with no changes is a broken invocation (e.g. a rejected flag /
        # version mismatch), not a phantom 'pass' and not a work roadblock the agent can solve.
        if rc != 0 and not diff:
            return ("fail", diff,
                    "claude exited {} with no changes (flag/version error?), "
                    "check the invocation.".format(rc))
        gate = build_gate_cmd(job, roe)
        if gate is None:
            return "pass", diff, "no gate configured (ROE test_cmd unset), review manually."
        gstatus, _gout, grc = _run_killable(["/bin/sh", "-c", gate], wt,
                                            getattr(_kill_ctx, "event", None))
        if gstatus == "killed":
            _discard_worktree(root, job.id)
            return "killed", None, "killed by operator, work discarded."
        if grc == 0:
            return "pass", diff, "gate passed."
        return _map_recovery(root, job, br,
                             _roadblock_or_advise(wt, job, roe, base_sha,   # failed gate: recover or roadblock
                                                  "gate FAILED ({})".format(gate)))
    except Exception as e:          # noqa: BLE001 — never let one job abort the run
        return "fail", None, "runner error: {}".format(e)


def render_deliverable_md(oc: "JobOutcome", repo: str) -> str:
    """The per-job deliverable record: what the job produced, its branch/diff, and how to take or
    drop it. Pure. For headless jobs the runner writes this; attended jobs write their own."""
    diff = ("{} files, +{}/-{}".format(oc.diff["files"], oc.diff["insertions"], oc.diff["deletions"])
            if oc.diff else "no changes recorded")
    lines = [
        "# Deliverable: {} ({})".format(oc.title, oc.id), "",
        "Repo: {}".format(repo),
        "Type: {} . DEFCON {} . outcome: {}".format(oc.type, oc.defcon, oc.outcome),
        "Branch: {}".format(oc.branch or "(none)"),
        "Diff: {}".format(diff), "",
        "## Summary", "", oc.note or "(no note)", "",
        "## Take it / drop it", "",
    ]
    if oc.merge_cmd:
        lines.append("Merge:   " + oc.merge_cmd)
    if oc.discard_cmd:
        lines.append("Discard: " + oc.discard_cmd)
    return "\n".join(lines) + "\n"


def write_job_deliverable(repo: str, oc: "JobOutcome") -> None:
    """Write the per-job deliverable record and stamp oc.deliverable with its repo-relative path.
    Only for jobs that actually ran (pass/fail); blocked/killed/limit produce no deliverable."""
    if oc.outcome not in ("pass", "fail"):
        return
    coa_io.write_deliverable(repo, oc.id, render_deliverable_md(oc, repo))
    oc.deliverable = coa_io.deliverable_rel(oc.id)


def render_roadblock_md(oc: "JobOutcome", repo: str) -> str:
    """The roadblock report: what happened, where it stopped, and how to pick it back up. Pure."""
    lines = [
        "# Roadblock: {} ({})".format(oc.title, oc.id), "",
        "Repo: {}".format(repo),
        "Type: {} . DEFCON {}".format(oc.type, oc.defcon),
        "Branch: {}".format(oc.branch or "(none)"), "",
        "## What happened", "", oc.note or "(no note)", "",
        "## Where it stopped / suggested fix", "",
        "Inspect the branch above for the partial work. Apply the fix, then "
        "`scorch coa resume {}` to continue and finish.".format(oc.id),
    ]
    return "\n".join(lines) + "\n"


def _notify_roadblock(oc: "JobOutcome") -> None:
    """Ping the developer that a job needs them (reuses the statusline notifier). Best-effort."""
    try:
        from . import statusline
        subtitle = (oc.title or oc.id)[:60].replace('"', "'")
        msg = (oc.note or "needs you").replace('"', "'")[:120]
        statusline._notify("Scorched Earth: job roadblocked", subtitle, msg)
    except Exception:  # noqa: BLE001 — a failed notification must never abort the run
        pass


def handle_roadblock(repo: str, oc: "JobOutcome") -> None:
    """On a roadblocked job: write the roadblock report, stamp oc.roadblock, and notify the
    developer. The advising-agent auto-solve (Stage 7) hooks in ahead of this."""
    if oc.outcome != "roadblocked":
        return
    coa_io.write_roadblock(repo, oc.id, render_roadblock_md(oc, repo))
    oc.roadblock = coa_io.roadblock_rel(oc.id)
    _notify_roadblock(oc)


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
        write_job_deliverable(repo, oc)       # per-job deliverable record (pass/fail only)
        if oc.outcome == "roadblocked":       # report + notify; the run continues to the next job
            handle_roadblock(repo, oc)
        rr.jobs[-1] = oc                      # replace the 'running' outcome with the finished one
        if oc.outcome in ("pass", "fail", "roadblocked", "killed"):
            # A finished job leaves the queue (same semantics as the cockpit engine): a
            # re-run must not silently re-execute it. Roadblocked comes back via `resume`,
            # not the queue. Blocked-* and limit jobs stay queued for a later run.
            coa_io.unqueue(repo, oc.id)
        if oc.outcome == "limit":
            rr.state = "halted"
            _persist()
            return rr
        _persist()
    rr.state = "done"
    _persist()
    return rr


def _summary(rr: RunResult) -> str:
    """Render a RunResult's job-outcome tally into a short human summary line."""
    n = {}
    for j in rr.jobs:
        n[j.outcome] = n.get(j.outcome, 0) + 1
    parts = []
    if n.get("pass"):              parts.append(f"{n['pass']} secured")
    if n.get("fail"):              parts.append(f"{n['fail']} cratered")
    if n.get("roadblocked"):       parts.append(f"{n['roadblocked']} roadblocked")
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
