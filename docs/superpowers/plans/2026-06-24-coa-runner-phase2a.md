# COA Queue-Runner (Phase 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the autonomous COA queue-runner — drains `.scorched/queue.json`, runs each job headless in a sandboxed worktree under ROE guardrails, and emits a live-updating After-Action Report (the morning-after review + live monitor).

**Architecture:** Pure budget/planning logic stays in `runner.py` (a `plan_run` function over the queue + envelope, unit-tested in isolation). The real-world per-job work (worktree, dependency pre-warm, sandboxed `claude -p`, test gate) is one injected `execute_job` callable so orchestration can be tested hermetically with a stub. Rendering follows the established template-injection pattern: `review_report.py` fills a self-contained `review_template.html` via a single `__REVIEW_JSON__` JSON blob. `core.py` and the statusline hot path are never touched.

**Tech Stack:** Python 3.8+ stdlib only (no third-party deps). Existing modules: `state.py` (JSON helpers, `STATE_DIR`), `jobs.py`, `roe.py`, `coa_io.py`, `advisor.py`, `coa_report.py`. Tests use the repo's home-grown `check()` harness (no pytest).

## Global Constraints

- **Stdlib only.** No third-party imports anywhere. Python floor is 3.8 (`from __future__ import annotations` at the top of every module; no `match` statements, no `X | Y` unions in annotations at runtime).
- **Never touch `core.py`, `calibrate.py`, `statusline.py`, or the statusline hot path.** The runner is an I/O-tier module like `state.py`.
- **Reuse `state.py` JSON helpers** (`st._read_json`, `st._write_json`) for any file under `~/.claude/scorched-earth/`. Per-repo files live under `<repo>/.scorched/` and use `coa_io`'s helpers.
- **Budget is always predictive/estimated.** The runner cannot read live `rate_limits`. Never label spend as measured; the review says "estimated".
- **Safety leash default is additive-only.** When a repo's ROE does not set `unattended_types`, the runner uses `SAFE_UNATTENDED = ["test", "docs", "perf", "audit"]`. Any other job type is `blocked-roe` and never executed.
- **Branch/path naming (verbatim):** per-job branch `scorched/<job-id>`; per-job worktree `<repo>/.scorched/wt/<job-id>`; run record `<repo>/.scorched/runs/<date>.json`; run HTML `<repo>/.scorched/runs/<date>.html`. Date is `YYYY-MM-DD` from `time.strftime`, passed in as a string (never call `Date()` in templates).
- **Tests:** add a new self-contained `tests/test_runner.py` following the exact pattern of `tests/test_advisor.py` (module-level `check(name, cond)`, prints `N checks passed.`, `raise SystemExit(1)` on any failure). Wire it into CI.

---

### Task 1: ROE + Job schema fields for the runner

**Files:**
- Modify: `src/scorched_earth/roe.py:10-21` (add three fields to `ROE`)
- Modify: `src/scorched_earth/jobs.py:20-56` (add `verify` to `Job` + `parse_jobs`)
- Test: `tests/test_runner.py` (new)

**Interfaces:**
- Produces: `ROE.test_cmd: Optional[str]`, `ROE.setup_cmd: Optional[str]`, `ROE.unattended_types: Optional[List[str]]`; `Job.verify: str` (default `""`). `roe_from_dict`/`merge_roe` already iterate `fields(ROE)`, so new fields flow through automatically.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runner.py`:

```python
"""Runner tests. Run: python3 tests/test_runner.py"""

import json
import os
import subprocess
import sys
import tempfile

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

passed = 0
failures = []


def check(name, cond):
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}")


# --- Task 1: schema fields --------------------------------------------------------
from scorched_earth.roe import ROE, roe_from_dict  # noqa: E402
from scorched_earth.jobs import parse_jobs  # noqa: E402

_r = roe_from_dict({"test_cmd": "pytest -q", "setup_cmd": "pip install -e .",
                    "unattended_types": ["test", "docs"]})
check("ROE carries runner fields",
      _r.test_cmd == "pytest -q" and _r.setup_cmd == "pip install -e ."
      and _r.unattended_types == ["test", "docs"])
check("ROE runner fields default to None",
      ROE().test_cmd is None and ROE().setup_cmd is None and ROE().unattended_types is None)

_j = parse_jobs([{"id": "a", "est_windows": 1, "value": 5, "verify": "make test"}])[0]
check("Job carries per-job verify override", _j.verify == "make test")
check("Job verify defaults empty", parse_jobs([{"id": "b", "est_windows": 1, "value": 5}])[0].verify == "")


print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `roe_from_dict` ignores unknown keys so `test_cmd` is `None`; `Job` has no `verify`. The `ROE carries runner fields` and `Job carries per-job verify override` checks fail (or AttributeError).

- [ ] **Step 3: Add the ROE fields**

In `src/scorched_earth/roe.py`, extend the `ROE` dataclass (after the existing `# task rules` block, before `# goal rules`):

```python
@dataclass
class ROE:
    # cost rules
    max_windows: Optional[float] = None             # cap total burn per COA (window-units)
    per_job_max_windows: Optional[float] = None     # reject any single job bigger than this
    min_weekly_left: float = 0.0                    # don't propose unless weekly-left above this
    # task rules
    allowed_types: Optional[List[str]] = None       # None = all types allowed (shapes the scan)
    # runner rules (Phase 2a — bound the autonomous executor)
    unattended_types: Optional[List[str]] = None    # types allowed to run unattended; None = SAFE default
    test_cmd: Optional[str] = None                  # post-job verification gate command
    setup_cmd: Optional[str] = None                 # dependency pre-warm command (runner-run, with network)
    # goal rules
    exclude_paths: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
```

- [ ] **Step 4: Add the Job `verify` field**

In `src/scorched_earth/jobs.py`, add `verify` to the dataclass (after `launch`):

```python
    launch: str = ""              # prompt/command to run it (Phase 1 hands this to the user)
    verify: str = ""              # per-job test-gate override (Phase 2 runner); falls back to ROE test_cmd
    status: str = "proposed"      # proposed | queued | done (Phase 2+ uses this)
```

And in `parse_jobs`, populate it (after the `launch=` line):

```python
            launch=d.get("launch", ""),
            verify=d.get("verify", ""),
            status=d.get("status", "proposed"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `4 checks passed.`

Also run the full suite to confirm no regression:
Run: `python3 tests/test_advisor.py && python3 tests/test_scorched.py`
Expected: both green (25 + 57).

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/roe.py src/scorched_earth/jobs.py tests/test_runner.py
git commit -m "feat(runner): ROE unattended_types/test_cmd/setup_cmd + Job verify"
```

---

### Task 2: Queue I/O (`.scorched/queue.json`)

**Files:**
- Modify: `src/scorched_earth/coa_io.py` (add queue helpers after `write_coa`)
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `_repo_dir(repo)`, `parse_jobs`, `st._read_json` (already imported in `coa_io`).
- Produces:
  - `read_queue(repo_path: str) -> List[Job]`
  - `write_queue(repo_path: str, jobs: List[Job]) -> str` (returns the queue.json path)
  - `enqueue(repo_path: str, jobs: List[Job]) -> List[Job]` (append, dedup by id preserving order, mark `status="queued"`, returns the full queue)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py` (before the final `print`):

```python
# --- Task 2: queue I/O ------------------------------------------------------------
import importlib  # noqa: E402
_home = tempfile.mkdtemp()
_repo = tempfile.mkdtemp()
_saved_env = dict(os.environ)
os.environ["HOME"] = _home
import scorched_earth.state as _st  # noqa: E402
importlib.reload(_st)
import scorched_earth.coa_io as _io  # noqa: E402
importlib.reload(_io)
from scorched_earth.jobs import Job  # noqa: E402

_q = [Job(id="j1", repo=_repo, title="One", type="test", est_windows=1.0, value=5),
      Job(id="j2", repo=_repo, title="Two", type="docs", est_windows=0.5, value=3)]
_io.write_queue(_repo, _q)
check("read_queue round-trips written jobs",
      [j.id for j in _io.read_queue(_repo)] == ["j1", "j2"])
check("write_queue marks jobs queued",
      all(j.status == "queued" for j in _io.read_queue(_repo)))

_io.enqueue(_repo, [Job(id="j2", repo=_repo, title="dup", type="docs", est_windows=0.5, value=3),
                    Job(id="j3", repo=_repo, title="Three", type="audit", est_windows=2.0, value=7)])
check("enqueue appends new and dedups by id, preserving order",
      [j.id for j in _io.read_queue(_repo)] == ["j1", "j2", "j3"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `AttributeError: module 'scorched_earth.coa_io' has no attribute 'write_queue'`.

- [ ] **Step 3: Implement the queue helpers**

Append to `src/scorched_earth/coa_io.py`:

```python
def _queue_path(repo_path: str) -> str:
    return os.path.join(_repo_dir(repo_path), "queue.json")


def _job_to_dict(j: Job) -> dict:
    return {
        "id": j.id, "repo": j.repo, "title": j.title, "type": j.type,
        "est_windows": j.est_windows, "value": j.value, "rationale": j.rationale,
        "launch": j.launch, "verify": j.verify, "status": j.status,
    }


def read_queue(repo_path: str) -> List[Job]:
    data = st._read_json(_queue_path(repo_path), [])
    return parse_jobs(data, repo=os.path.realpath(os.path.expanduser(repo_path)))


def write_queue(repo_path: str, jobs: List[Job]) -> str:
    os.makedirs(_repo_dir(repo_path), exist_ok=True)
    path = _queue_path(repo_path)
    for j in jobs:
        j.status = "queued"
    with open(path, "w") as f:
        import json as _json
        _json.dump([_job_to_dict(j) for j in jobs], f, indent=2)
    return path


def enqueue(repo_path: str, jobs: List[Job]) -> List[Job]:
    existing = read_queue(repo_path)
    seen = {j.id for j in existing}
    for j in jobs:
        if j.id not in seen:
            existing.append(j)
            seen.add(j.id)
    write_queue(repo_path, existing)
    return existing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `7 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_io.py tests/test_runner.py
git commit -m "feat(runner): .scorched/queue.json read/write/enqueue"
```

---

### Task 3: Predictive run planner (pure)

**Files:**
- Create: `src/scorched_earth/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Job`, `ROE`.
- Produces:
  - `SAFE_UNATTENDED: List[str]` = `["test", "docs", "perf", "audit"]`
  - `plan_run(jobs: List[Job], envelope: float, roe: ROE) -> Tuple[List[Tuple[Job, str]], float]` — pure. Walks the queue in order; each job gets a disposition in `{"run", "blocked-roe", "skipped-budget"}`. Returns `(dispositions, predicted_spend)`. ROE-block takes precedence over budget; once a `run` job won't fit, that job and all later non-blocked jobs are `skipped-budget`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py`:

```python
# --- Task 3: predictive planner ---------------------------------------------------
from scorched_earth.runner import plan_run, SAFE_UNATTENDED  # noqa: E402
from scorched_earth.roe import roe_from_dict as _rfd  # noqa: E402

_pjobs = [
    Job(id="t", repo="r", title="t", type="test", est_windows=1.0, value=5),
    Job(id="ref", repo="r", title="ref", type="refactor", est_windows=0.5, value=9),  # not in SAFE
    Job(id="d", repo="r", title="d", type="docs", est_windows=1.0, value=4),
    Job(id="a", repo="r", title="a", type="audit", est_windows=2.0, value=8),
]
_disp, _spent = plan_run(_pjobs, envelope=2.5, roe=ROE())
_by_id = {j.id: d for j, d in _disp}
check("plan_run runs additive jobs that fit, in order",
      _by_id["t"] == "run" and _by_id["d"] == "run")
check("plan_run blocks non-SAFE types regardless of budget", _by_id["ref"] == "blocked-roe")
check("plan_run marks the overflow job skipped-budget", _by_id["a"] == "skipped-budget")
check("plan_run predicted spend counts only run jobs", _spent == 2.0)
check("SAFE_UNATTENDED is additive-only",
      set(SAFE_UNATTENDED) == {"test", "docs", "perf", "audit"})
check("explicit unattended_types widens the leash",
      {j.id: d for j, d in plan_run([_pjobs[1]], 5.0, _rfd({"unattended_types": ["refactor"]}))[0]}["ref"] == "run")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'scorched_earth.runner'`.

- [ ] **Step 3: Create `runner.py` with the planner**

Create `src/scorched_earth/runner.py`:

```python
"""The COA queue-runner: drains .scorched/queue.json, executes each job headless in a
sandboxed git worktree under the ROE leash, and emits a live After-Action Report. I/O tier
(subprocess + git); never imported by the statusline hot path. The budget/planning core
(`plan_run`) is pure and unit-tested; the per-job real-world work is one injected callable."""

from __future__ import annotations

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `13 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py tests/test_runner.py
git commit -m "feat(runner): pure plan_run predictive accounting + SAFE_UNATTENDED leash"
```

---

### Task 4: RunResult model, envelope/staleness, and run-record I/O

**Files:**
- Modify: `src/scorched_earth/runner.py` (add dataclasses + envelope/staleness helpers)
- Modify: `src/scorched_earth/coa_io.py` (add run-record read/write)
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces (in `runner.py`):
  - `@dataclass JobOutcome` with fields: `seq:int, id:str, title:str, type:str, tier:str, outcome:str, est_windows:float, branch:Optional[str]=None, diff:Optional[dict]=None, note:str="", merge_cmd:Optional[str]=None, discard_cmd:Optional[str]=None`
  - `@dataclass RunResult` with fields: `generated_at:str, state:str, repo:str, verdict:str, note:str, available_windows:float, spent_estimated:float, jobs:List[JobOutcome]=field(default_factory=list), refresh_seconds:int=6, sector:str="SECTOR 07"`
  - `read_envelope(state: Optional[dict], roe: ROE) -> Optional[float]` — returns the run envelope (windows) or `None` if the snapshot is missing/stale (refuse-rather-than-guess).
  - `is_stale(state: Optional[dict], now: int) -> bool`
- Produces (in `coa_io.py`):
  - `write_run_record(repo_path: str, record: dict, date: str) -> str` (writes `.scorched/runs/<date>.json`, returns path)
  - `read_run_record(repo_path: str, date: Optional[str] = None) -> Optional[dict]` (latest by filename if `date` is None)
  - `runs_dir(repo_path: str) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py`:

```python
# --- Task 4: RunResult + envelope/staleness + run-record I/O ----------------------
from scorched_earth.runner import JobOutcome, RunResult, read_envelope, is_stale  # noqa: E402
from dataclasses import asdict as _asdict  # noqa: E402

_now = 1_000_000
_fresh = {"snapshot": {"five_hour_reset": _now + 3600, "seven_day_pct": 40},
          "recommendation": {"windows_left": 3.0, "level": "green"}}
_stale = {"snapshot": {"five_hour_reset": _now - 10, "seven_day_pct": 40},
          "recommendation": {"windows_left": 3.0, "level": "green"}}
check("is_stale: fresh snapshot is usable", not is_stale(_fresh, _now))
check("is_stale: elapsed-window snapshot is stale", is_stale(_stale, _now))
check("is_stale: missing snapshot is stale", is_stale(None, _now))
check("read_envelope returns windows_left when fresh", read_envelope(_fresh, ROE(), _now) == 3.0)
check("read_envelope caps at ROE max_windows",
      read_envelope(_fresh, _rfd({"max_windows": 2.0}), _now) == 2.0)
check("read_envelope refuses (None) on stale snapshot", read_envelope(_stale, ROE(), _now) is None)

_rr = RunResult(generated_at="2026-06-24", state="done", repo=_repo, verdict="green",
                note="1 secured.", available_windows=3.0, spent_estimated=1.0,
                jobs=[JobOutcome(seq=1, id="j1", title="One", type="test", tier="M",
                                 outcome="pass", est_windows=1.0, branch="scorched/j1")])
_path = _io.write_run_record(_repo, _asdict(_rr), "2026-06-24")
check("write_run_record persists under .scorched/runs",
      os.path.exists(_path) and "runs" in _path and "2026-06-24" in _path)
check("read_run_record reads the latest record",
      _io.read_run_record(_repo)["jobs"][0]["id"] == "j1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `ImportError: cannot import name 'JobOutcome'`.

- [ ] **Step 3: Add dataclasses + envelope/staleness to `runner.py`**

Add imports and code to `src/scorched_earth/runner.py`. Update the import block and append:

```python
from dataclasses import dataclass, field
```

(merge into the existing `from typing import` area — add `dataclass, field` import near the top). Then append:

```python
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
    return reset is not None and reset < now


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
```

- [ ] **Step 4: Add run-record I/O to `coa_io.py`**

Append to `src/scorched_earth/coa_io.py`:

```python
def runs_dir(repo_path: str) -> str:
    return os.path.join(_repo_dir(repo_path), "runs")


def write_run_record(repo_path: str, record: dict, date: str) -> str:
    out = runs_dir(repo_path)
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{date}.json")
    with open(path, "w") as f:
        import json as _json
        _json.dump(record, f, indent=2)
    return path


def read_run_record(repo_path: str, date: Optional[str] = None):
    out = runs_dir(repo_path)
    if date is None:
        try:
            stamps = sorted(p[:-5] for p in os.listdir(out) if p.endswith(".json"))
        except OSError:
            return None
        if not stamps:
            return None
        date = stamps[-1]
    rec = st._read_json(os.path.join(out, f"{date}.json"), None)
    return rec
```

Add `Optional` to the `typing` import at the top of `coa_io.py` (`from typing import List, Optional, Tuple`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `21 checks passed.`

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/runner.py src/scorched_earth/coa_io.py tests/test_runner.py
git commit -m "feat(runner): RunResult/JobOutcome, envelope+staleness guard, run-record I/O"
```

---

### Task 5: Review renderer + self-contained stub template

**Files:**
- Create: `src/scorched_earth/review_template.html` (minimal valid stub; the Claude-design version drops in later with no code change)
- Create: `src/scorched_earth/review_report.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `RunResult`, `JobOutcome`.
- Produces:
  - `aar_dict(rr: RunResult) -> dict` — the template-shaped (camelCase) data object.
  - `render_review_md(rr: RunResult) -> str`
  - `render_review_html(rr: RunResult) -> str` — fills `__REVIEW_JSON__` in `review_template.html`; the page auto-refreshes only while `rr.state == "running"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py`:

```python
# --- Task 5: review render --------------------------------------------------------
from scorched_earth.review_report import aar_dict, render_review_md, render_review_html  # noqa: E402

_running = RunResult(generated_at="2026-06-24 03:14", state="running", repo=_repo,
                     verdict="green", note="1 working.", available_windows=2.5,
                     spent_estimated=1.0,
                     jobs=[JobOutcome(seq=1, id="t", title="Tests", type="test", tier="M",
                                      outcome="running", est_windows=1.0, branch="scorched/t")])
_d = aar_dict(_running)
check("aar_dict camelCases the template contract",
      _d["state"] == "running" and _d["envelope"]["spentEstimated"] == 1.0
      and _d["jobs"][0]["estWindows"] == 1.0)
_md = render_review_md(_running)
check("render_review_md lists job + outcome + estimated label",
      "Tests" in _md and "running" in _md.lower() and "estimated" in _md.lower())
_html_run = render_review_html(_running)
check("render_review_html substitutes the data token",
      "__REVIEW_JSON__" not in _html_run and _html_run.lstrip().lower().startswith("<!doctype html"))
check("render_review_html auto-refreshes while running",
      "http-equiv" in _html_run.lower() and "refresh" in _html_run.lower())
_done = RunResult(generated_at="2026-06-24 03:20", state="done", repo=_repo, verdict="green",
                  note="done.", available_windows=2.5, spent_estimated=1.0, jobs=_running.jobs)
check("render_review_html omits refresh when done",
      "http-equiv" not in render_review_html(_done).lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'scorched_earth.review_report'`.

- [ ] **Step 3: Create the stub template**

Create `src/scorched_earth/review_template.html` (a valid, self-contained placeholder — the design handoff in `docs/design/2026-06-24-coa-review-hud-brief.md` replaces this file later; the Python contract is the `const AAR` blob and the `__REVIEW_JSON__` token):

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scorched Earth — After-Action Report</title>
<!--
  AFTER-ACTION REPORT (AAR) — the COA runner's live monitor + morning-after debrief.
  STUB TEMPLATE: replace with the Claude-design HTML (see docs/design brief). Contract:
  all data flows through `const AAR = __REVIEW_JSON__`. Python substitutes the token.
  When AAR.state === "running", the renderer also injects a <meta http-equiv="refresh">.
-->
<style>
  body{background:#0b0705;color:#f4e4c8;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;padding:24px}
  h1{letter-spacing:.2em} .job{border:1px solid #6b4a2b;padding:8px;margin:6px 0}
  .pass{color:#9fd36a}.fail{color:#ff6a1f}.running{color:#ffd24a}
  @media (prefers-reduced-motion: reduce){*{animation:none!important}}
</style>
</head><body>
<h1>AFTER-ACTION REPORT</h1>
<div id="run"></div><div id="jobs"></div>
<script>
const AAR = __REVIEW_JSON__;
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
document.getElementById('run').textContent =
  AAR.repo + ' · ' + AAR.note + ' · ~' + AAR.envelope.spentEstimated +
  ' of ' + AAR.envelope.available + ' windows (estimated)';
document.getElementById('jobs').innerHTML = AAR.jobs.map(j =>
  '<div class="job '+esc(j.outcome)+'">#'+j.seq+' ['+esc(j.outcome)+'] '+esc(j.title)+
  (j.branch?' — '+esc(j.branch):'')+'</div>').join('');
</script>
</body></html>
```

- [ ] **Step 4: Create `review_report.py`**

Create `src/scorched_earth/review_report.py`:

```python
"""Render a RunResult to Markdown (the record) and HTML (the live monitor + final debrief),
both from one structured source so they never disagree. The HTML fills the bundled
review_template.html by injecting one JSON blob (same pattern as coa_report.py / report.py).
While the run is in progress the page auto-refreshes; when done it settles, no refresh."""

from __future__ import annotations

import json
import os

from .runner import RunResult

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "review_template.html")


def _job_obj(j) -> dict:
    return {
        "seq": j.seq, "id": j.id, "title": j.title, "type": (j.type or "").upper(),
        "tier": j.tier, "outcome": j.outcome, "branch": j.branch,
        "estWindows": round(j.est_windows, 1), "diff": j.diff, "note": j.note,
        "mergeCmd": j.merge_cmd, "discardCmd": j.discard_cmd,
    }


def aar_dict(rr: RunResult) -> dict:
    return {
        "generatedAt": rr.generated_at,
        "state": rr.state,
        "refreshSeconds": rr.refresh_seconds,
        "sector": rr.sector,
        "repo": rr.repo,
        "verdict": (rr.verdict or "unknown").upper(),
        "note": rr.note,
        "envelope": {"available": round(rr.available_windows, 1),
                     "spentEstimated": round(rr.spent_estimated, 1)},
        "jobs": [_job_obj(j) for j in rr.jobs],
    }


def render_review_md(rr: RunResult) -> str:
    lines = [f"# After-Action Report — {rr.generated_at}", "",
             f"{rr.repo} · {rr.note}",
             f"~{rr.spent_estimated:.1f} of {rr.available_windows:.1f} windows (estimated)", "",
             "| # | job | type | outcome | branch | diff |",
             "|---|-----|------|---------|--------|------|"]
    for j in rr.jobs:
        d = (f"+{j.diff['insertions']}/-{j.diff['deletions']} ({j.diff['files']}f)"
             if j.diff else "—")
        lines.append(f"| {j.seq} | {j.title} | {j.type} | {j.outcome} | {j.branch or '—'} | {d} |")
    return "\n".join(lines) + "\n"


def render_review_html(rr: RunResult) -> str:
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    html = template.replace("__REVIEW_JSON__", json.dumps(aar_dict(rr)))
    if rr.state == "running":
        meta = f'<meta http-equiv="refresh" content="{rr.refresh_seconds}">'
        html = html.replace("<head>", "<head>\n" + meta, 1)
    return html
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `27 checks passed.`

- [ ] **Step 6: Commit**

```bash
git add src/scorched_earth/review_template.html src/scorched_earth/review_report.py tests/test_runner.py
git commit -m "feat(runner): AAR review renderer (md+html) + self-contained stub template"
```

---

### Task 6: Default `execute_job` (command builders + real per-job work)

**Files:**
- Modify: `src/scorched_earth/runner.py` (add builders + `execute_job`)
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces:
  - `worktree_path(repo: str, job_id: str) -> str` → `<repo>/.scorched/wt/<job-id>`
  - `branch_name(job_id: str) -> str` → `scorched/<job-id>`
  - `build_claude_cmd(job: Job, worktree: str) -> List[str]` — the sandboxed headless invocation (prelude + job.launch).
  - `build_gate_cmd(job: Job, roe: ROE) -> Optional[str]` — `job.verify` if set, else `roe.test_cmd`, else `None`.
  - `merge_cmd(repo, job_id) -> str`, `discard_cmd(repo, job_id) -> str` — copyable git commands for the review.
  - `execute_job(repo: str, job: Job, roe: ROE) -> Tuple[str, Optional[dict], str]` — returns `(outcome, diff, note)` where outcome is `"pass"` or `"fail"`. Default implementation; `run_queue` (Task 7) injects a stub in tests.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py`:

```python
# --- Task 6: command builders -----------------------------------------------------
from scorched_earth.runner import (worktree_path, branch_name, build_claude_cmd,  # noqa: E402
                                    build_gate_cmd, merge_cmd, discard_cmd)

_jb = Job(id="cov", repo=_repo, title="Coverage", type="test", est_windows=1.0, value=5,
          launch="Raise coverage to 90%, TDD.")
check("branch_name namespaces under scorched/", branch_name("cov") == "scorched/cov")
check("worktree_path lives under .scorched/wt", worktree_path(_repo, "cov").endswith("/.scorched/wt/cov"))
_cmd = build_claude_cmd(_jb, worktree_path(_repo, "cov"))
check("build_claude_cmd is a headless claude invocation carrying the launch",
      _cmd[0] == "claude" and "-p" in _cmd and any("Raise coverage" in a for a in _cmd))
check("build_claude_cmd prelude forbids push", any("do not push" in a.lower() for a in _cmd))
check("build_gate_cmd prefers per-job verify",
      build_gate_cmd(Job(id="x", repo="r", title="x", type="test", est_windows=1, value=1,
                         verify="make test"), _rfd({"test_cmd": "pytest"})) == "make test")
check("build_gate_cmd falls back to ROE test_cmd",
      build_gate_cmd(_jb, _rfd({"test_cmd": "pytest -q"})) == "pytest -q")
check("build_gate_cmd is None when neither set", build_gate_cmd(_jb, ROE()) is None)
check("merge_cmd / discard_cmd reference the branch",
      "scorched/cov" in merge_cmd(_repo, "cov") and "scorched/cov" in discard_cmd(_repo, "cov"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `ImportError: cannot import name 'worktree_path'`.

- [ ] **Step 3: Add builders + `execute_job` to `runner.py`**

Add to the imports at the top of `runner.py`:

```python
import os
import subprocess
```

Append:

```python
def branch_name(job_id: str) -> str:
    return f"scorched/{job_id}"


def worktree_path(repo: str, job_id: str) -> str:
    return os.path.join(os.path.realpath(os.path.expanduser(repo)), ".scorched", "wt", job_id)


def merge_cmd(repo: str, job_id: str) -> str:
    return f"git -C {repo} merge {branch_name(job_id)}"


def discard_cmd(repo: str, job_id: str) -> str:
    return (f"git -C {repo} worktree remove --force {worktree_path(repo, job_id)} && "
            f"git -C {repo} branch -D {branch_name(job_id)}")


_PRELUDE = (
    "You are running UNATTENDED inside an isolated git worktree. Operating orders: "
    "work ONLY in this worktree; make additive, focused changes; when done, commit with a "
    "clear message. DO NOT push. DO NOT touch other repositories or files outside the worktree. "
    "Task follows.\n\n"
)


def build_claude_cmd(job: Job, worktree: str) -> List[str]:
    """Headless, sandboxed claude invocation. The sandbox (filesystem -> worktree, network ->
    API only) is configured via Claude Code settings/flags confirmed in planning; here we emit
    the canonical headless form. The job's launch is the task; the prelude is the leash."""
    return [
        "claude", "-p", _PRELUDE + (job.launch or job.title),
        "--dangerously-skip-permissions",
        "--add-dir", worktree,
    ]


def build_gate_cmd(job: Job, roe: ROE) -> Optional[str]:
    return job.verify or roe.test_cmd or None


def _git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo_root, *args], capture_output=True, text=True)


def _diffstat(worktree: str) -> Optional[dict]:
    p = _git(worktree, "diff", "--numstat", "HEAD~1..HEAD")
    if p.returncode != 0 or not p.stdout.strip():
        return None
    files = ins = dele = 0
    for line in p.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            ins += int(parts[0]); dele += int(parts[1]); files += 1
    return {"files": files, "insertions": ins, "deletions": dele}


def execute_job(repo: str, job: Job, roe: ROE) -> Tuple[str, Optional[dict], str]:
    """Real per-job work: worktree -> pre-warm deps -> sandboxed claude -p -> test gate.
    Returns (outcome, diff, note). Outcome is 'pass' or 'fail'. The orchestration in run_queue
    treats any exception here as a 'fail' so one bad job never aborts the run."""
    root = os.path.realpath(os.path.expanduser(repo))
    wt = worktree_path(repo, job.id)
    br = branch_name(job.id)
    _git(root, "worktree", "add", "-b", br, wt, "HEAD")
    try:
        if roe.setup_cmd:                                   # pre-warm with network (trusted, runner-run)
            subprocess.run(roe.setup_cmd, cwd=wt, shell=True, capture_output=True, text=True)
        subprocess.run(build_claude_cmd(job, wt), cwd=wt, capture_output=True, text=True)
        diff = _diffstat(wt)
        gate = build_gate_cmd(job, roe)
        if gate is None:
            return "pass", diff, "no gate configured (ROE test_cmd unset) — review manually."
        g = subprocess.run(gate, cwd=wt, shell=True, capture_output=True, text=True)
        if g.returncode == 0:
            return "pass", diff, "gate passed."
        return "fail", diff, f"gate FAILED ({gate}) — branch kept for triage."
    except Exception as e:                                  # noqa: BLE001 — never let one job abort the run
        return "fail", None, f"runner error: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `36 checks passed.`

(The builder unit tests cover command construction. The subprocess body of `execute_job` is exercised end-to-end by Task 7's injected-stub orchestration tests and by manual verification; it is not unit-tested against a live `claude`.)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py tests/test_runner.py
git commit -m "feat(runner): execute_job — worktree, pre-warm, sandboxed claude -p, test gate"
```

---

### Task 7: `run_queue` orchestration (live re-render, injected executor)

**Files:**
- Modify: `src/scorched_earth/runner.py` (add `run_queue`)
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `plan_run`, `read_envelope`, `is_stale`, `JobOutcome`, `RunResult`, `execute_job`, `merge_cmd`, `discard_cmd`; `coa_io.read_queue`, `coa_io.write_run_record`; `review_report.render_review_html`, `render_review_md`.
- Produces:
  - `run_queue(repo, state, *, now, date, execute=None, on_step=None) -> Optional[RunResult]` — returns `None` (refusal) when stale/no-envelope. `execute` defaults to `execute_job`; tests inject a stub `execute(repo, job, roe) -> (outcome, diff, note)`. `on_step(rr)` is called after every job with the current `RunResult` (live re-render hook). Persists the record + HTML after each step.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py`:

```python
# --- Task 7: run_queue orchestration (hermetic, stub executor) --------------------
from scorched_earth.runner import run_queue  # noqa: E402

# queue: a runnable test job, a refactor (ROE-blocked), a big audit (won't fit 1.5 envelope)
_io.write_queue(_repo, [
    Job(id="t1", repo=_repo, title="Tests", type="test", est_windows=1.0, value=5,
        launch="add tests"),
    Job(id="r1", repo=_repo, title="Refactor", type="refactor", est_windows=0.2, value=9),
    Job(id="a1", repo=_repo, title="Audit", type="audit", est_windows=3.0, value=8),
])
_steps = []
def _stub_exec(repo, job, roe):
    return ("pass", {"files": 2, "insertions": 30, "deletions": 4}, "gate passed.")
_state_ok = {"snapshot": {"five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
             "recommendation": {"windows_left": 1.5, "level": "green"}}
_rr = run_queue(_repo, _state_ok, now=1, date="2026-06-24",
                execute=_stub_exec, on_step=lambda rr: _steps.append(rr.state))
_out = {j.id: j.outcome for j in _rr.jobs}
check("run_queue executes the runnable additive job", _out["t1"] == "pass")
check("run_queue blocks the refactor via ROE leash", _out["r1"] == "blocked-roe")
check("run_queue marks the oversize audit skipped-budget", _out["a1"] == "skipped-budget")
check("run_queue final state is done", _rr.state == "done")
check("run_queue re-renders live (on_step fired per job)", len(_steps) >= 3)
check("run_queue records estimated spend, not measured", _rr.spent_estimated == 1.0)
check("run_queue attaches merge/discard to executed job",
      _rr.jobs[0].branch == "scorched/t1" and "scorched/t1" in (_rr.jobs[0].merge_cmd or ""))
check("run_queue persisted a run record + html",
      os.path.exists(os.path.join(_io.runs_dir(_repo), "2026-06-24.json"))
      and os.path.exists(os.path.join(_io.runs_dir(_repo), "2026-06-24.html")))

_refused = run_queue(_repo, _stale, now=_now, date="2026-06-24", execute=_stub_exec)
check("run_queue refuses on a stale snapshot", _refused is None)

def _boom_exec(repo, job, roe):
    raise RuntimeError("claude died")
_io.write_queue(_repo, [Job(id="t2", repo=_repo, title="T2", type="test", est_windows=0.5, value=5)])
_rr2 = run_queue(_repo, _state_ok, now=1, date="2026-06-25", execute=_boom_exec)
check("run_queue turns an executor crash into a failed job, not an abort",
      _rr2 is not None and _rr2.jobs[0].outcome == "fail")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `ImportError: cannot import name 'run_queue'`.

- [ ] **Step 3: Implement `run_queue`**

Add to `runner.py` imports:

```python
from . import coa_io
from . import review_report
```

(Place these imports at the top with the other `from .` imports. They are safe — no import cycle: `coa_io` imports `jobs`/`roe`/`state`, and `review_report` imports `runner` only for the dataclasses, which are defined before this function is used at runtime. To avoid a circular import at module load, import `review_report` lazily inside the function instead.)

Append:

```python
def _outcome_for(job: Job, seq: int, disposition: str) -> JobOutcome:
    note = {"blocked-roe": f"type '{job.type}' not in unattended leash — not run.",
            "skipped-budget": "no budget left when reached."}[disposition]
    return JobOutcome(seq=seq, id=job.id, title=job.title, type=job.type, tier=job.tier,
                      outcome=disposition, est_windows=job.est_windows, note=note)


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
        running = JobOutcome(seq=i, id=job.id, title=job.title, type=job.type, tier=job.tier,
                             outcome="running", est_windows=job.est_windows,
                             branch=branch_name(job.id))
        rr.jobs.append(running)
        _persist()                                    # live: this job is in progress
        outcome, diff, note = execute(repo, job, roe)
        spent += job.est_windows
        running.outcome = outcome
        running.diff = diff
        running.note = note
        running.merge_cmd = merge_cmd(repo_disp, job.id)
        running.discard_cmd = discard_cmd(repo_disp, job.id)
        rr.spent_estimated = spent
        _persist()

    rr.state = "done"
    rr.spent_estimated = spent
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `47 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py tests/test_runner.py
git commit -m "feat(runner): run_queue orchestration with live re-render + injected executor"
```

---

### Task 8: CLI verbs `coa queue` / `coa run` / `coa review`

**Files:**
- Modify: `bin/scorch` (add a `coa` verb group dispatched from `main`)
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `runner.run_queue`, `coa_io.read_queue/enqueue/load_jobs/read_run_record`, `review_report.render_review_html`, `advisor.match`, `st.load_state`.
- Produces: subcommands under `scorch coa …`:
  - `coa queue --all | <id...>` — enqueue from the latest matched COA.
  - `coa run` — drain the queue (refuses cleanly if no snapshot / stale).
  - `coa review [--merge <id> | --discard <id>]` — render+open the latest AAR, or run a merge/discard helper.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py` (subprocess style, like `test_advisor.py`):

```python
# --- Task 8: CLI verbs (subprocess, temp HOME) ------------------------------------
os.environ.clear(); os.environ.update(_saved_env)
_cli_env = dict(os.environ)
_cli_env["HOME"] = tempfile.mkdtemp()
_scorch = os.path.join(os.path.dirname(__file__), "..", "bin", "scorch")
_cli_repo = tempfile.mkdtemp()
subprocess.run([sys.executable, _scorch, "link", _cli_repo], capture_output=True, text=True, env=_cli_env)

_run = subprocess.run([sys.executable, _scorch, "coa", "run"], capture_output=True, text=True, env=_cli_env)
check("scorch coa run refuses cleanly with no snapshot",
      _run.returncode == 0 and ("no" in _run.stdout.lower() or "snapshot" in _run.stdout.lower()))
_rev = subprocess.run([sys.executable, _scorch, "coa", "review"], capture_output=True, text=True, env=_cli_env)
check("scorch coa review reports cleanly when there's no run yet",
      _rev.returncode == 0 and ("no" in _rev.stdout.lower()))
_que = subprocess.run([sys.executable, _scorch, "coa", "queue", "--all", _cli_repo],
                      capture_output=True, text=True, env=_cli_env)
check("scorch coa queue runs without error (empty COA -> nothing queued)",
      _que.returncode == 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `scorch coa run` currently falls through to argparse and errors (unrecognized) or the `coa` verb is not handled; the checks fail.

- [ ] **Step 3: Wire the `coa` verb group in `bin/scorch`**

In `bin/scorch`, change the dispatch line in `main` (currently `if raw and raw[0] in ("link", "unlink", "advise", "roe"):`) to also route `coa`:

```python
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] == "coa":
        return _coa_run_cli(raw[1:])
    if raw and raw[0] in ("link", "unlink", "advise", "roe"):
        return _coa_cli(raw)
```

Add the new handler near `_coa_cli`:

```python
def _coa_run_cli(rest):
    """`scorch coa <queue|run|review> …` — the Phase 2 queue-runner surface."""
    import time as _time
    from scorched_earth import coa_io, advisor, runner, review_report
    sub = rest[0] if rest else "review"
    args = rest[1:]
    date = _time.strftime("%Y-%m-%d", _time.localtime())

    if sub == "queue":
        all_flag = "--all" in args
        ids = [a for a in args if not a.startswith("-")]
        repo = ids.pop(0) if ids and os.path.isdir(os.path.expanduser(ids[0])) else "."
        state = st.load_state()
        rec = (state or {}).get("recommendation") or {}
        wl = rec.get("windows_left")
        if wl is None:
            print("No live budget reading yet — open a Claude Code session, then queue.")
            return 0
        roe = coa_io.load_roe(repo)
        coa = advisor.match(wl, coa_io.load_jobs(repo), roe)
        pick = coa.queue if (all_flag or not ids) else [j for j in coa.queue if j.id in ids]
        if not pick:
            print("Nothing to queue (the latest COA produced no eligible jobs).")
            return 0
        q = coa_io.enqueue(repo, pick)
        print(f"Queued {len(pick)} job(s); {len(q)} in {repo}/.scorched/queue.json.")
        return 0

    if sub == "run":
        repos = [a for a in args if not a.startswith("-")] or coa_io.list_repos() or ["."]
        state = st.load_state()
        now = int(_time.time())
        if runner.is_stale(state, now):
            print("No fresh budget snapshot — open a Claude Code session so the statusline "
                  "captures a reading, then run again. (The runner can't read usage live.)")
            return 0
        for repo in repos:
            if not coa_io.read_queue(repo):
                continue
            rr = runner.run_queue(repo, state, now=now, date=date)
            if rr is None:
                print(f"{repo}: refused (stale snapshot).")
                continue
            html = os.path.join(coa_io.runs_dir(repo), f"{date}.html")
            print(f"{repo}: {rr.note}")
            _open_file(html)
        return 0

    # review (default)
    repo = (args[0] if args and os.path.isdir(os.path.expanduser(args[0])) else
            (coa_io.list_repos()[0] if coa_io.list_repos() else "."))
    if "--merge" in args or "--discard" in args:
        flag = "--merge" if "--merge" in args else "--discard"
        jid = args[args.index(flag) + 1]
        cmd = (runner.merge_cmd(repo, jid) if flag == "--merge"
               else runner.discard_cmd(repo, jid))
        print(f"Run this to {flag[2:]} {jid}:\n  {cmd}")
        return 0
    rec = coa_io.read_run_record(repo)
    if not rec:
        print("No run on record yet. Queue jobs (scorch coa queue) then run (scorch coa run).")
        return 0
    html = os.path.join(coa_io.runs_dir(repo), f"{rec['generated_at']}.html")
    if os.path.exists(html):
        _open_file(html)
    print(f"Latest run: {rec.get('note', '')}")
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — `50 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add bin/scorch tests/test_runner.py
git commit -m "feat(runner): scorch coa queue/run/review CLI surface"
```

---

### Task 9: Wire CI + docs

**Files:**
- Modify: `.github/workflows/tests.yml` (run `tests/test_runner.py`)
- Modify: `commands/coa.md` (document the queue → run → review flow)
- Modify: `CLAUDE.md` (add `runner.py` + `review_report.py` to the architecture list)
- Modify: `docs/playbook.md` (test counts + status)

**Interfaces:** none (docs/CI only).

- [ ] **Step 1: Add the runner tests to CI**

In `.github/workflows/tests.yml`, after the `Advisor tests` step:

```yaml
      - name: Runner tests
        run: python3 tests/test_runner.py
```

- [ ] **Step 2: Document the runner flow in `commands/coa.md`**

Append a section to `commands/coa.md` describing the Phase 2 loop (read the existing file first to match its voice/format):

```markdown
## Autonomous execution (Phase 2)

Once a COA exists you can have Scorched Earth burn it for you, unattended:

- `scorch coa queue --all` — enqueue the matched jobs into `.scorched/queue.json`.
- `scorch coa run` — drain the queue: each job runs headless in a sandboxed git worktree
  (`scorched/<job-id>`), additive-only by ROE leash, commit-not-push, with a test gate after.
  Budget is spent predictively (the runner can't read usage live); it stops when the envelope
  is exhausted. Opens a live After-Action Report that fills in as jobs complete.
- `scorch coa review` — reopen the latest After-Action Report. `--merge <id>` / `--discard <id>`
  print the git command to take or drop a job's branch.

Safety: only additive/verifiable job types run unattended (widen via ROE `unattended_types`);
nothing is pushed or merged without you. Set `test_cmd` and `setup_cmd` in the repo's ROE.
```

- [ ] **Step 3: Update `CLAUDE.md` architecture list**

Add two lines to the Architecture section of `CLAUDE.md` (after the `coa_io.py` line):

```markdown
- `src/scorched_earth/runner.py` — COA queue-runner (Phase 2a): drains `.scorched/queue.json`, runs each job headless in a sandboxed worktree under the ROE leash (`plan_run` is the pure predictive-budget core; the per-job work is the injected `execute_job`). I/O tier; never on the statusline hot path.
- `src/scorched_earth/review_report.py` + `coa_template`-style `review_template.html` — renders the live/After-Action Report (md + HTML) from one `RunResult`; auto-refreshes while running, settles when done.
```

- [ ] **Step 4: Update `docs/playbook.md` test counts + status**

Update the test-count line (`docs/playbook.md:116-117`) to include the runner checks, and refresh the Current Status section to note Phase 2a (runner) is built. Read the file first; change the count line to:

```markdown
57 unit checks passing (`python3 tests/test_scorched.py`) + 25 advisor checks
(`python3 tests/test_advisor.py`) + 50 runner checks (`python3 tests/test_runner.py`);
```

(Use the actual final count printed by `tests/test_runner.py`.)

- [ ] **Step 5: Run the full suite + confirm**

Run: `python3 tests/test_scorched.py && python3 tests/test_advisor.py && python3 tests/test_runner.py`
Expected: all three green (57 + 25 + 50).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/tests.yml commands/coa.md CLAUDE.md docs/playbook.md
git commit -m "docs+ci(runner): wire test_runner into CI; document the queue/run/review flow"
```

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-06-24-coa-runner-phase2-design.md`):
- Persisted queue + CLI to populate → Task 2 (`queue.json`), Task 8 (`coa queue`). ✓
- Sequential drain sized to burn → Task 7 (`run_queue` loops in order), Task 3 (`plan_run`). ✓
- Worktree + branch isolation, commit-not-push → Task 6 (`execute_job` + prelude). ✓
- Pre-warm network model (Option A) → Task 6 (`setup_cmd` run by runner before sandboxed claude). ✓
- Sandboxed headless `claude -p` → Task 6 (`build_claude_cmd`); exact sandbox flag confirmation flagged in spec/Global Constraints as a planning lookup. ✓
- ROE leash (additive-only default) → Task 1 (`unattended_types`), Task 3 (`SAFE_UNATTENDED`). ✓
- Test gate, keep-branch-on-failure, continue → Task 6 (`build_gate_cmd`/gate), Task 7 (failure → outcome, run continues). ✓
- Predictive budget + staleness refusal → Task 4 (`read_envelope`/`is_stale`), Task 7 (refusal path). ✓
- HTML + MD review; live auto-refresh monitor → Task 5 (renderer + template), Task 7 (`_persist` re-renders per job; refresh while running). ✓
- Keep `core.py`/statusline untouched, runner is I/O tier → no task modifies them. ✓
- Testing via pure parts + injected fake-spawn → Tasks 3/4/5 pure; Task 7 stub executor. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; the `review_template.html` stub is explicitly a working placeholder (valid, renders the data) that the design handoff replaces with no code change — not a placeholder-in-the-plan. ✓

**3. Type consistency:** `JobOutcome`/`RunResult` field names match between Task 4 (definition), Task 5 (`aar_dict` reads `j.est_windows`, `rr.spent_estimated`, etc.), and Task 7 (constructs them). `read_envelope(state, roe, now)` signature is consistent between Task 4 (final form) and Task 7 (call site). `execute(repo, job, roe) -> (outcome, diff, note)` matches between Task 6 (`execute_job`), Task 7 (call + stub), tests. ✓
