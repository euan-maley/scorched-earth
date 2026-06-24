# COA Live Cockpit (Phase 2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scorch coa --serve` — a localhost server hosting a live, interactive kanban cockpit that drives the Phase 2a runner via an event-driven `advance` step (no background loop).

**Architecture:** A stdlib `ThreadingHTTPServer` bound to 127.0.0.1 with a one-time token serves one cockpit HTML and pushes board state over SSE. Browser mutations (queue/unqueue/reorder/run/stop) are token-guarded POSTs naming job-ids only. A single `Engine` object holds shared state behind a lock and runs an event-driven `advance` step on a worker thread; `advance` picks one eligible affordable job, runs it through the **reused Phase 2a `execute_job`**, and chains on completion. Budget is a refreshing envelope checked at pick time. `core.py`/statusline are never touched.

**Tech Stack:** Python 3.8+ stdlib only — `http.server`, `socketserver.ThreadingHTTPServer`, `threading`, `queue.Queue`, `secrets`, `json`. Reuses Phase 2a `runner.py` (`execute_job`, `JobOutcome`, `RunResult`, `read_envelope`, `merge_cmd`, `discard_cmd`, `branch_name`, `_allowed_unattended`) and `coa_io.py` (`read_queue`, `enqueue`, `write_run_record`, `read_run_record`, `runs_dir`, `load_jobs`, `load_roe`, `list_repos`), and `review_report.render_review_html`.

## Global Constraints

- **Stdlib only.** No third-party imports. Python 3.8 floor: `from __future__ import annotations` at the top of every module; no `match`; no runtime `X | Y` unions.
- **Never touch `core.py`, `calibrate.py`, `statusline.py`, or the statusline hot path.**
- **Execution path is unchanged.** Every job still runs through Phase 2a `execute_job` (sandboxed worktree, pre-warm, gate). `--serve` adds a *trigger* surface, never a new execution path. Do NOT reimplement job execution.
- **Security (mandatory, verbatim):** bind host is `127.0.0.1` only (never `0.0.0.0`). A one-time token (`secrets.token_urlsafe(32)`) is minted at launch and required on EVERY request — query param `?t=<token>` for `GET /` and `GET /events`, header `X-Scorch-Token: <token>` for every POST. Missing/wrong token → HTTP 403. The server runs **only the agent-supplied `launch` for a job-id present in the queue/COA it loaded** — a command string in a request body is ignored. ROE (`unattended_types`, cost caps) is enforced server-side at pick time.
- **Event-driven, no loop.** The engine is a single `advance` step invoked only on: Run, job-completion (the chain), and queue-while-idle. Four guards: one-job-at-a-time (global BUSY flag), remove-from-queue-on-pick, terminate-by-default (idle when nothing eligible), failed-job-dropped-not-retried.
- **Thread safety.** All shared `Engine` state is guarded by a single `threading.Lock`. The `advance` chain runs on ONE worker thread; HTTP handlers never run jobs inline.
- **Budget honesty.** Spend is predictive/estimated, never claimed measured. Snapshot read via `st.load_state()`; staleness/None refusal reuses `read_envelope`.
- **Tests:** extend the home-grown harness. Pure/engine tests go in a new `tests/test_cockpit.py` (same `check()` pattern as `tests/test_runner.py`). Wire it into CI.
- **Naming (verbatim):** module `coa_serve.py`; template `cockpit_template.html` with tokens `__COCKPIT_TOKEN__` and `__COCKPIT_JSON__`; CLI verb `scorch coa --serve [<repo>]`; SSE event name `board`; the snapshot timestamp field is `state["snapshot"]["now"]`.

---

### Task 1: Extract `run_one` from `run_queue`

**Files:**
- Modify: `src/scorched_earth/runner.py` (`run_queue` around lines 290-345)
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces: `run_one(repo, job, roe, repo_disp, seq, *, execute, on_running=None) -> JobOutcome` — builds the "running" `JobOutcome`, calls `on_running(oc)` if given (live two-phase), runs `execute` (its own try/except → "fail" on raise), fills outcome/diff/note/merge_cmd/discard_cmd, returns the finished `JobOutcome`. Pure orchestration over the injected `execute`; no persistence.
- `run_queue` is refactored to call `run_one` (behavior unchanged).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py` (before the final `print`):

```python
# --- Task 1 (2b): run_one extraction ----------------------------------------------
from scorched_earth.runner import run_one  # noqa: E402

_phase = []
def _ex_ok(repo, job, roe):
    return ("pass", {"files": 1, "insertions": 5, "deletions": 0}, "gate passed.")
_oc = run_one(_repo, Job(id="z1", repo=_repo, title="Z", type="test", est_windows=1.0, value=5),
              ROE(), _repo, 3, execute=_ex_ok, on_running=lambda oc: _phase.append(oc.outcome))
check("run_one fires on_running with a 'running' outcome first", _phase == ["running"])
check("run_one returns the finished outcome with branch + merge/discard",
      _oc.outcome == "pass" and _oc.branch == "scorched/z1"
      and "scorched/z1" in (_oc.merge_cmd or "") and _oc.diff["files"] == 1)

def _ex_boom(repo, job, roe):
    raise RuntimeError("died")
_ocb = run_one(_repo, Job(id="z2", repo=_repo, title="Z2", type="test", est_windows=0.5, value=5),
               ROE(), _repo, 4, execute=_ex_boom)
check("run_one turns an executor raise into a fail outcome", _ocb.outcome == "fail")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_runner.py`
Expected: FAIL — `ImportError: cannot import name 'run_one'`.

- [ ] **Step 3: Add `run_one` and refactor `run_queue`**

In `src/scorched_earth/runner.py`, add `run_one` just above `run_queue`:

```python
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
```

Then in `run_queue`, replace the `disp == "run"` body (the block from `running = JobOutcome(...)` through `rr.spent_estimated = spent` / `_persist()`) with:

```python
        oc = run_one(repo, job, roe, repo_disp, i, execute=execute,
                     on_running=lambda r: (rr.jobs.append(r), _persist()))
        rr.jobs[-1] = oc                      # replace the 'running' outcome with the finished one
        spent += job.est_windows
        rr.spent_estimated = spent
        _persist()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_runner.py`
Expected: PASS — runner count +3, and the existing run_queue orchestration checks still green (regression: `run_queue` behaves identically).

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py tests/test_runner.py
git commit -m "refactor(cockpit): extract run_one; run_queue builds on it"
```

---

### Task 2: `pick_next` + `EnvelopeTracker` (pure)

**Files:**
- Modify: `src/scorched_earth/runner.py`
- Test: `tests/test_cockpit.py` (new)

**Interfaces:**
- Produces:
  - `pick_next(queue: List[Job], available: float, roe: ROE) -> Optional[Job]` — first queued job that is ROE-allowed (`_allowed_unattended`) AND fits `available` (`est_windows <= available + _EPS`). First-fit with skip-ahead (unlike `plan_run`'s no-backfill — the interactive board lets a smaller card run when the top doesn't fit). `None` if none.
  - `class EnvelopeTracker` — refreshing budget. `__init__(self, roe)`; `available(self, state, now) -> Optional[float]` re-syncs (`spent=0`) when `state["snapshot"]["now"]` differs from the synced timestamp, then returns `read_envelope(state, roe, now) - spent` (or `None` if stale); `charge(self, est)` adds to predictive spend.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cockpit.py`:

```python
"""Cockpit (Phase 2b) tests. Run: python3 tests/test_cockpit.py"""

import json
import os
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


# --- Task 2: pick_next + EnvelopeTracker ------------------------------------------
from scorched_earth.jobs import Job  # noqa: E402
from scorched_earth.roe import ROE, roe_from_dict  # noqa: E402
from scorched_earth.runner import pick_next, EnvelopeTracker  # noqa: E402

_q = [Job(id="big", repo="r", title="big", type="test", est_windows=3.0, value=5),
      Job(id="ref", repo="r", title="ref", type="refactor", est_windows=0.2, value=9),  # ROE-blocked
      Job(id="ok",  repo="r", title="ok",  type="docs", est_windows=1.0, value=4)]
check("pick_next skips too-big top and ROE-blocked, returns first that fits",
      pick_next(_q, 1.5, ROE()).id == "ok")
check("pick_next returns None when nothing fits", pick_next(_q, 0.1, ROE()) is None)

_fresh = {"snapshot": {"now": 1000, "five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
          "recommendation": {"windows_left": 2.0, "level": "green"}}
_tr = EnvelopeTracker(ROE())
check("EnvelopeTracker available = windows_left initially", _tr.available(_fresh, 1) == 2.0)
_tr.charge(0.5)
check("EnvelopeTracker subtracts predictive spend", _tr.available(_fresh, 1) == 1.5)
_adv = {"snapshot": {"now": 2000, "five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
        "recommendation": {"windows_left": 1.8, "level": "green"}}
check("EnvelopeTracker re-syncs (spent->0) when snapshot timestamp advances",
      _tr.available(_adv, 1) == 1.8)
_stale = {"snapshot": {"now": 3000, "seven_day_pct": 50},
          "recommendation": {"windows_left": 1.0}}
check("EnvelopeTracker returns None on stale snapshot", _tr.available(_stale, 1) is None)


print(f"\n{passed} checks passed.")
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `ImportError: cannot import name 'pick_next'`.

- [ ] **Step 3: Implement in `runner.py`**

Append to `src/scorched_earth/runner.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — `6 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/runner.py tests/test_cockpit.py
git commit -m "feat(cockpit): pick_next first-fit + refreshing EnvelopeTracker"
```

---

### Task 3: `coa_io` queue ops — `unqueue` + `reorder`

**Files:**
- Modify: `src/scorched_earth/coa_io.py` (after `enqueue`)
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Produces:
  - `unqueue(repo_path, job_id) -> List[Job]` — remove the job with `id == job_id` from `queue.json`; returns the new queue.
  - `reorder(repo_path, ids) -> List[Job]` — rewrite `queue.json` to the order in `ids` (only ids currently queued, in that order); any currently-queued job NOT named in `ids` is appended after, preserving its prior order. Returns the new queue.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py`:

```python
# --- Task 3: queue ops ------------------------------------------------------------
import importlib  # noqa: E402
_home = tempfile.mkdtemp(); _repo = tempfile.mkdtemp()
os.environ["HOME"] = _home
import scorched_earth.state as _st  # noqa: E402
importlib.reload(_st)
import scorched_earth.coa_io as _io  # noqa: E402
importlib.reload(_io)

_io.write_queue(_repo, [Job(id="a", repo=_repo, title="A", type="test", est_windows=1, value=5),
                        Job(id="b", repo=_repo, title="B", type="docs", est_windows=1, value=4),
                        Job(id="c", repo=_repo, title="C", type="perf", est_windows=1, value=3)])
check("unqueue removes by id", [j.id for j in _io.unqueue(_repo, "b")] == ["a", "c"])
check("unqueue persisted", [j.id for j in _io.read_queue(_repo)] == ["a", "c"])
_io.write_queue(_repo, [Job(id="a", repo=_repo, title="A", type="test", est_windows=1, value=5),
                        Job(id="b", repo=_repo, title="B", type="docs", est_windows=1, value=4),
                        Job(id="c", repo=_repo, title="C", type="perf", est_windows=1, value=3)])
check("reorder applies the given order", [j.id for j in _io.reorder(_repo, ["c", "a", "b"])] == ["c", "a", "b"])
check("reorder appends un-named queued jobs after",
      [j.id for j in _io.reorder(_repo, ["b"])] == ["b", "c", "a"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `AttributeError: module 'scorched_earth.coa_io' has no attribute 'unqueue'`.

- [ ] **Step 3: Implement in `coa_io.py`**

Append to `src/scorched_earth/coa_io.py`:

```python
def unqueue(repo_path: str, job_id: str) -> List[Job]:
    kept = [j for j in read_queue(repo_path) if j.id != job_id]
    write_queue(repo_path, kept)
    return kept


def reorder(repo_path: str, ids: List[str]) -> List[Job]:
    current = read_queue(repo_path)
    by_id = {j.id: j for j in current}
    ordered = [by_id[i] for i in ids if i in by_id]
    named = set(ids)
    ordered += [j for j in current if j.id not in named]   # keep un-named jobs, prior order
    write_queue(repo_path, ordered)
    return ordered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — `10 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_io.py tests/test_cockpit.py
git commit -m "feat(cockpit): coa_io unqueue + reorder queue ops"
```

---

### Task 4: Board-state assembler

**Files:**
- Modify: `src/scorched_earth/coa_io.py`
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Produces: `board_state(repo_path) -> dict` with shape
  `{"repo": <abspath>, "name": <basename>, "proposed": [jd...], "queued": [jd...], "finished": [od...]}`
  where `proposed` = `load_jobs(repo)` minus any id present in the queue or finished; `queued` = `read_queue(repo)`; `finished` = the `jobs` of the latest run record (`read_run_record(repo)`) with a terminal outcome (pass/fail). Each `jd` (job dict) = `{id,title,type,tier,est_windows,value}`; each `od` (outcome dict) is the stored run-record job dict as-is.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py`:

```python
# --- Task 4: board_state assembler ------------------------------------------------
os.makedirs(os.path.join(_repo, ".scorched"), exist_ok=True)
with open(os.path.join(_repo, ".scorched", "jobs.json"), "w") as f:
    json.dump([{"id": "p1", "title": "Prop1", "type": "test", "est_windows": 1, "value": 5},
               {"id": "q1", "title": "Queued1", "type": "docs", "est_windows": 1, "value": 4},
               {"id": "d1", "title": "Done1", "type": "perf", "est_windows": 1, "value": 3}], f)
_io.write_queue(_repo, [Job(id="q1", repo=_repo, title="Queued1", type="docs", est_windows=1, value=4)])
_io.write_run_record(_repo, {"generated_at": "2026-06-24", "state": "done", "repo": _repo,
                             "jobs": [{"id": "d1", "title": "Done1", "type": "perf", "tier": "M",
                                       "outcome": "pass", "est_windows": 1.0, "branch": "scorched/d1"}]},
                     "2026-06-24")
_bs = _io.board_state(_repo)
check("board_state proposes only un-queued/un-finished jobs", [j["id"] for j in _bs["proposed"]] == ["p1"])
check("board_state queued reflects the queue", [j["id"] for j in _bs["queued"]] == ["q1"])
check("board_state finished reflects the last run record", [j["id"] for j in _bs["finished"]] == ["d1"])
check("board_state carries repo name", _bs["name"] == os.path.basename(_repo))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `AttributeError: ... 'board_state'`.

- [ ] **Step 3: Implement in `coa_io.py`**

Append to `src/scorched_earth/coa_io.py`:

```python
def _job_brief(j: Job) -> dict:
    return {"id": j.id, "title": j.title, "type": j.type, "tier": j.tier,
            "est_windows": j.est_windows, "value": j.value}


def board_state(repo_path: str) -> dict:
    ap = os.path.realpath(os.path.expanduser(repo_path))
    queued = read_queue(repo_path)
    rec = read_run_record(repo_path) or {}
    finished = [j for j in (rec.get("jobs") or []) if j.get("outcome") in ("pass", "fail")]
    spoken = {j.id for j in queued} | {j.get("id") for j in finished}
    proposed = [_job_brief(j) for j in load_jobs(repo_path) if j.id not in spoken]
    return {"repo": ap, "name": os.path.basename(ap),
            "proposed": proposed, "queued": [_job_brief(j) for j in queued],
            "finished": finished}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — `14 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_io.py tests/test_cockpit.py
git commit -m "feat(cockpit): board_state assembler (proposed/queued/finished)"
```

---

### Task 5: The `Engine` (event-driven advance, no HTTP)

**Files:**
- Create: `src/scorched_earth/coa_serve.py`
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Produces `class Engine`:
  - `__init__(self, repos, *, execute=None, broadcast=None, load_state=None, now=None)` — `repos` is a list of repo paths; `execute` defaults to `runner.execute_job`; `broadcast()` is called (no args) after every state change; `load_state`/`now` are injectable for tests (default `st.load_state` / `time.time`).
  - `state_json(self) -> dict` — `{"repos": [board_state...], "running": {"repo","id"}|None, "busy": bool}`.
  - `queue(self, repo, job_id)` / `unqueue(self, repo, job_id)` / `reorder(self, repo, ids)` — mutate via `coa_io`, broadcast, and (for `queue`) trigger `advance(repo)`.
  - `run(self, repo)` — trigger `advance(repo)`.
  - `stop(self)` — set the stop flag.
  - `advance(self, repo)` — the event-driven step (below). Runs the job inline in the calling thread (the HTTP layer in Task 6 calls it on a worker thread). Re-entrancy is prevented by the BUSY flag under the lock.
- All shared state guarded by `self._lock`. Job execution happens OUTSIDE the lock (only state reads/writes are locked).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py`:

```python
# --- Task 5: Engine (event-driven advance) ----------------------------------------
from scorched_earth.coa_serve import Engine  # noqa: E402

def _mk_repo(jobs):
    r = tempfile.mkdtemp()
    _io.write_queue(r, jobs)
    return r

_ran = []
def _exec(repo, job, roe):
    _ran.append(job.id)
    return ("pass", {"files": 1, "insertions": 3, "deletions": 0}, "ok")
_STATE = {"snapshot": {"now": 1, "five_hour_reset": 9_999_999_999, "seven_day_pct": 50},
          "recommendation": {"windows_left": 2.5, "level": "green"}}
_r = _mk_repo([Job(id="t1", repo=".", title="T1", type="test", est_windows=1.0, value=5),
               Job(id="r1", repo=".", title="R1", type="refactor", est_windows=0.2, value=9),  # ROE block
               Job(id="t2", repo=".", title="T2", type="test", est_windows=1.0, value=4),
               Job(id="t3", repo=".", title="T3", type="test", est_windows=1.0, value=3)])  # over budget
_beats = []
_eng = Engine([_r], execute=_exec, broadcast=lambda: _beats.append(1),
              load_state=lambda: _STATE, now=lambda: 1)
_eng.run(_r)
check("engine drains the affordable additive cards in order", _ran == ["t1", "t2"])
check("engine skips the ROE-blocked card (refactor never ran)", "r1" not in _ran)
check("engine stops when the next card is over budget (t3 left queued)",
      [j.id for j in _io.read_queue(_r)] == ["r1", "t3"])
check("engine broadcast fired across the run", len(_beats) >= 4)
check("engine not busy after draining", _eng.state_json()["busy"] is False)

# crash containment + no-retry
_ran2 = []
def _boom(repo, job, roe):
    _ran2.append(job.id)
    if job.id == "x1":
        raise RuntimeError("died")
    return ("pass", None, "ok")
_r2 = _mk_repo([Job(id="x1", repo=".", title="X1", type="test", est_windows=0.5, value=5),
                Job(id="x2", repo=".", title="X2", type="test", est_windows=0.5, value=4)])
_eng2 = Engine([_r2], execute=_boom, load_state=lambda: _STATE, now=lambda: 1)
_eng2.run(_r2)
check("engine: a crashing job is dropped (not retried) and the chain continues",
      _ran2 == ["x1", "x2"] and _io.read_queue(_r2) == [])

# stop halts the chain
_ran3 = []
def _exec_stop(repo, job, roe):
    _ran3.append(job.id)
    _eng3.stop()                     # request stop after the first job
    return ("pass", None, "ok")
_r3 = _mk_repo([Job(id="s1", repo=".", title="S1", type="test", est_windows=0.5, value=5),
                Job(id="s2", repo=".", title="S2", type="test", est_windows=0.5, value=4)])
_eng3 = Engine([_r3], execute=_exec_stop, load_state=lambda: _STATE, now=lambda: 1)
_eng3.run(_r3)
check("engine: stop halts the chain after the current job", _ran3 == ["s1"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'scorched_earth.coa_serve'`.

- [ ] **Step 3: Create `coa_serve.py` with the Engine**

Create `src/scorched_earth/coa_serve.py`:

```python
"""The COA live cockpit: a localhost server hosting an event-driven engine that drives the
Phase 2a runner. The Engine holds shared board state behind a lock and runs an `advance`
step (no background loop) on a worker thread; HTTP/SSE wiring is added in Task 6. I/O tier;
never imported by the statusline hot path."""

from __future__ import annotations

import os
import threading
import time

from . import coa_io
from . import runner
from . import state as st


class Engine:
    """Event-driven cockpit engine. `advance` runs ONE eligible affordable job and chains on
    completion. Re-entrancy is blocked by a global BUSY flag (one job at a time across all
    repos, since budget is one pool). Terminates by default: empty/over-budget/ROE-blocked
    queue or stop -> idle. A crashing job is recorded fail, dropped, and the chain continues."""

    def __init__(self, repos, *, execute=None, broadcast=None, load_state=None, now=None):
        self.repos = [os.path.realpath(os.path.expanduser(r)) for r in repos]
        self._execute = execute or runner.execute_job
        self._broadcast = broadcast or (lambda: None)
        self._load_state = load_state or st.load_state
        self._now = now or (lambda: int(time.time()))
        self._lock = threading.Lock()
        self._busy = False
        self._stop = False
        self._running = None                       # {"repo","id"} or None
        self._trackers = {}                        # repo -> EnvelopeTracker
        self._results = {}                         # repo -> RunResult (accumulating)

    # ---- public mutations (called by HTTP handlers) ----
    def queue(self, repo, job_id):
        from .jobs import parse_jobs
        # promote a proposed job into the queue by id
        jobs = {j.id: j for j in coa_io.load_jobs(repo)}
        if job_id in jobs:
            coa_io.enqueue(repo, [jobs[job_id]])
        self._broadcast()
        self.advance(repo)

    def unqueue(self, repo, job_id):
        coa_io.unqueue(repo, job_id)
        self._broadcast()

    def reorder(self, repo, ids):
        coa_io.reorder(repo, ids)
        self._broadcast()

    def run(self, repo):
        self.advance(repo)

    def stop(self):
        with self._lock:
            self._stop = True

    # ---- state ----
    def state_json(self):
        with self._lock:
            running = dict(self._running) if self._running else None
            busy = self._busy
        return {"repos": [coa_io.board_state(r) for r in self.repos],
                "running": running, "busy": busy}

    # ---- the event-driven step ----
    def advance(self, repo):
        repo = os.path.realpath(os.path.expanduser(repo))
        # one-at-a-time guard + stop check, atomically
        with self._lock:
            if self._busy or self._stop:
                return
            roe = coa_io.load_roe(repo)
            tracker = self._trackers.get(repo)
            if tracker is None:
                tracker = runner.EnvelopeTracker(roe)
                self._trackers[repo] = tracker
            avail = tracker.available(self._load_state(), self._now())
            if avail is None:
                return                              # stale/absent snapshot -> refuse
            job = runner.pick_next(coa_io.read_queue(repo), avail, roe)
            if job is None:
                return                              # idle: nothing eligible/affordable
            self._busy = True
            self._running = {"repo": repo, "id": job.id}
            coa_io.unqueue(repo, job.id)            # remove-on-pick: can never run twice
            rr = self._results.get(repo)
            if rr is None:
                rr = runner.RunResult(
                    generated_at=time.strftime("%Y-%m-%d", time.localtime(self._now())),
                    state="running", repo=repo, verdict="unknown", note="",
                    available_windows=avail, spent_estimated=0.0)
                self._results[repo] = rr
            seq = len(rr.jobs) + 1
        self._broadcast()

        # execute OUTSIDE the lock (long-running, sandboxed)
        oc = runner.run_one(repo, job, roe, repo, seq, execute=self._execute)

        with self._lock:
            tracker.charge(job.est_windows)
            rr.jobs.append(oc)
            rr.spent_estimated = tracker.spent
            self._persist(repo, rr)
            self._busy = False
            self._running = None
            stopped = self._stop
        self._broadcast()

        if not stopped:
            self.advance(repo)                      # chain to the next card

    def _persist(self, repo, rr):
        from . import review_report
        rr.note = runner._summary(rr)
        coa_io.write_run_record(repo, runner._dataclass_dict(rr), rr.generated_at)
        with open(os.path.join(coa_io.runs_dir(repo), rr.generated_at + ".html"), "w") as f:
            f.write(review_report.render_review_html(rr))
```

(Note: `advance` chains via recursion; depth is bounded by the queue length per run and each step does real work — not a tight loop. If a very long queue makes recursion depth a concern, the reviewer may convert the tail `self.advance(repo)` into a `while` over the same guarded step — behavior identical.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — `+6` engine checks. (If the recursive `advance` chain is a concern for very long queues, it is acceptable here — queues are small; note it for the reviewer.)

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_serve.py tests/test_cockpit.py
git commit -m "feat(cockpit): event-driven Engine.advance (4 runaway guards, refreshing budget)"
```

---

### Task 6: HTTP server — token, routing, SSE

**Files:**
- Modify: `src/scorched_earth/coa_serve.py`
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Produces:
  - `make_server(engine, token, *, render=None) -> (httpd, port)` — builds a `ThreadingHTTPServer` bound to `("127.0.0.1", 0)` whose handler enforces the token and routes the endpoints. `render(token, state_dict) -> str` produces the cockpit HTML for `GET /`; defaults to a minimal inline page in Task 6 (Task 7 supplies the real template renderer). Returns the server and the chosen port. Does NOT call `serve_forever` (the caller/tests control the loop).
  - The handler: `GET /?t=` → cockpit HTML (403 if bad token); `GET /state?t=` → `engine.state_json()`; `GET /events?t=` → SSE stream (registers a client `queue.Queue`, writes `event: board` frames); `POST /queue|/unqueue|/reorder|/run|/stop` with `X-Scorch-Token` header → calls the matching `engine` method from the JSON body (job-ids only; any `cmd`/`launch` field in the body is ignored), returns `{"ok": true}`.
  - SSE broadcast: the Engine's `broadcast` is wired to push `engine.state_json()` to every registered client queue.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py`:

```python
# --- Task 6: HTTP server (token, routing, SSE) ------------------------------------
import http.client  # noqa: E402
import threading as _threading  # noqa: E402
from scorched_earth.coa_serve import make_server  # noqa: E402

_r6 = _mk_repo([Job(id="g1", repo=".", title="G1", type="test", est_windows=1.0, value=5)])
_eng6 = Engine([_r6], execute=_exec, load_state=lambda: _STATE, now=lambda: 1)
_TOKEN = "secret-token-xyz"
_httpd, _port = make_server(_eng6, _TOKEN)
_srv_thread = _threading.Thread(target=_httpd.serve_forever, daemon=True)
_srv_thread.start()

def _get(path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", _port, timeout=3)
    c.request("GET", path, headers=headers or {}); r = c.getresponse(); body = r.read(); c.close()
    return r.status, body

def _post(path, payload, token):
    c = http.client.HTTPConnection("127.0.0.1", _port, timeout=3)
    hdr = {"Content-Type": "application/json"}
    if token: hdr["X-Scorch-Token"] = token
    c.request("POST", path, body=json.dumps(payload), headers=hdr)
    r = c.getresponse(); body = r.read(); c.close()
    return r.status, body

check("server binds loopback only", _httpd.server_address[0] == "127.0.0.1")
check("GET / without token is 403", _get("/")[0] == 403)
check("GET / with token serves html", _get(f"/?t={_TOKEN}")[0] == 200)
check("POST without token is 403", _post("/queue", {"repo": _r6, "id": "g1"}, None)[0] == 403)
check("POST with a raw command field runs no command (job-id only)",
      _post("/run", {"repo": _r6, "cmd": "rm -rf /"}, _TOKEN)[0] == 200)
_st6, _b6 = _get(f"/state?t={_TOKEN}")
check("GET /state returns board json", _st6 == 200 and b"repos" in _b6)
# /queue mutates the queue file
_io.write_queue(_r6, [Job(id="g1", repo=".", title="G1", type="test", est_windows=1.0, value=5)])
_post("/reorder", {"repo": _r6, "ids": ["g1"]}, _TOKEN)
check("POST /reorder returns ok", _post("/reorder", {"repo": _r6, "ids": ["g1"]}, _TOKEN)[0] == 200)
_httpd.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `ImportError: cannot import name 'make_server'`.

- [ ] **Step 3: Implement the server in `coa_serve.py`**

Add imports at the top of `coa_serve.py`:

```python
import json
import queue as _queue
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer
```

Append:

```python
class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _default_render(token, state):
    # Minimal page; Task 7 replaces this with the cockpit template renderer.
    return ("<!doctype html><meta charset=utf-8><title>COA Cockpit</title>"
            "<body>cockpit (token ok)</body>").encode("utf-8")


def make_server(engine, token, *, render=None):
    render = render or _default_render
    clients = []                                   # list[queue.Queue] of SSE subscribers
    clients_lock = threading.Lock()

    def _broadcast():
        snap = engine.state_json()
        with clients_lock:
            dead = []
            for q in clients:
                try:
                    q.put_nowait(snap)
                except Exception:                  # noqa: BLE001
                    dead.append(q)
            for q in dead:
                clients.remove(q)
    engine._broadcast = _broadcast                 # wire engine -> SSE

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):                 # silence default stderr logging
            pass

        def _tok_q(self):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            return (qs.get("t") or [None])[0]

        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if self._tok_q() != token:
                self._send(403, b'{"error":"forbidden"}'); return
            if path == "/":
                self._send(200, render(token, engine.state_json()), "text/html; charset=utf-8")
            elif path == "/state":
                self._send(200, json.dumps(engine.state_json()).encode("utf-8"))
            elif path == "/events":
                self._sse()
            else:
                self._send(404, b'{"error":"not found"}')

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = _queue.Queue()
            with clients_lock:
                clients.append(q)
            try:
                self.wfile.write(b"event: board\ndata: "
                                 + json.dumps(engine.state_json()).encode("utf-8") + b"\n\n")
                self.wfile.flush()
                while True:
                    snap = q.get()
                    self.wfile.write(b"event: board\ndata: "
                                     + json.dumps(snap).encode("utf-8") + b"\n\n")
                    self.wfile.flush()
            except Exception:                      # noqa: BLE001 — client disconnected
                pass
            finally:
                with clients_lock:
                    if q in clients:
                        clients.remove(q)

        def do_POST(self):
            if self.headers.get("X-Scorch-Token") != token:
                self._send(403, b'{"error":"forbidden"}'); return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, b'{"error":"bad json"}'); return
            path = self.path.split("?", 1)[0]
            repo = body.get("repo")
            # job-ids ONLY: any cmd/launch field in the body is never read.
            try:
                if path == "/queue":
                    threading.Thread(target=engine.queue, args=(repo, body.get("id")),
                                     daemon=True).start()
                elif path == "/unqueue":
                    engine.unqueue(repo, body.get("id"))
                elif path == "/reorder":
                    engine.reorder(repo, list(body.get("ids") or []))
                elif path == "/run":
                    threading.Thread(target=engine.run, args=(repo,), daemon=True).start()
                elif path == "/stop":
                    engine.stop()
                else:
                    self._send(404, b'{"error":"not found"}'); return
            except Exception as e:                 # noqa: BLE001
                self._send(500, json.dumps({"error": str(e)}).encode("utf-8")); return
            self._send(200, b'{"ok":true}')

    httpd = _ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return httpd, httpd.server_address[1]
```

(`/queue` and `/run` start the engine on a worker thread so the POST returns immediately while the `advance` chain runs; `/unqueue`/`/reorder`/`/stop` are quick and run inline.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — `+7` server checks.

- [ ] **Step 5: Commit**

```bash
git add src/scorched_earth/coa_serve.py tests/test_cockpit.py
git commit -m "feat(cockpit): ThreadingHTTPServer with token, routing, SSE; job-ids only"
```

---

### Task 7: Cockpit template renderer + stub template + design brief

**Files:**
- Create: `src/scorched_earth/cockpit_template.html` (self-contained stub; the Claude-design board replaces it later)
- Modify: `src/scorched_earth/coa_serve.py` (add `render_cockpit`)
- Create: `docs/design/2026-06-24-coa-cockpit-brief.md` (design handoff)
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Produces: `render_cockpit(token, state) -> bytes` — reads `cockpit_template.html`, substitutes `__COCKPIT_TOKEN__` with the token (JSON-encoded string) and `__COCKPIT_JSON__` with `json.dumps(state)`, returns UTF-8 bytes. Wired as the `render` for `make_server` when launched for real.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py`:

```python
# --- Task 7: cockpit renderer -----------------------------------------------------
from scorched_earth.coa_serve import render_cockpit  # noqa: E402

_html = render_cockpit("tok-123", {"repos": [{"repo": _r6, "name": "g", "proposed": [],
                                              "queued": [{"id": "g1"}], "finished": []}],
                                   "running": None, "busy": False})
_txt = _html.decode("utf-8")
check("render_cockpit substitutes both tokens",
      "__COCKPIT_TOKEN__" not in _txt and "__COCKPIT_JSON__" not in _txt)
check("render_cockpit embeds token + state",
      "tok-123" in _txt and "g1" in _txt and _txt.lstrip().lower().startswith("<!doctype html"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `ImportError: cannot import name 'render_cockpit'`.

- [ ] **Step 3: Create the stub template**

Create `src/scorched_earth/cockpit_template.html` (valid, self-contained placeholder — the Claude-design board in `docs/design/2026-06-24-coa-cockpit-brief.md` replaces this with no Python change; the contract is `const TOKEN = __COCKPIT_TOKEN__;` and `const STATE = __COCKPIT_JSON__;`):

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scorched Earth — COA Cockpit</title>
<!-- STUB cockpit. Replace with the Claude-design board (see docs/design brief). Contract:
     const TOKEN = __COCKPIT_TOKEN__;  const STATE = __COCKPIT_JSON__;  POSTs carry the
     X-Scorch-Token header; GET /events is the SSE stream (event: board). Render STATE.repos
     into columns (proposed/queued/running/finished); never send a command, only job ids. -->
<style>
  body{background:#0b0705;color:#f4e4c8;font-family:ui-monospace,Menlo,Consolas,monospace;padding:20px}
  .col{display:inline-block;vertical-align:top;width:23%;min-width:180px}
  .card{border:1px solid #6b4a2b;padding:6px;margin:4px 0}
  @media (prefers-reduced-motion: reduce){*{animation:none!important}}
</style></head><body>
<h1>COA COCKPIT</h1><div id="board"></div>
<script>
const TOKEN = __COCKPIT_TOKEN__;
const STATE = __COCKPIT_JSON__;
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function render(state){
  document.getElementById('board').innerHTML = state.repos.map(r =>
    '<h2>'+esc(r.name)+(state.busy?' · BUSY':'')+'</h2>' +
    [['PROPOSED','proposed'],['QUEUED','queued'],['RUNNING','running'],['DONE','finished']]
      .map(([lab,key])=>'<div class=col><b>'+lab+'</b>'+
        ((key==='running'? (state.running&&state.running.repo===r.repo?[state.running]:[]) : r[key])||[])
          .map(j=>'<div class=card>'+esc(j.id||j.title||'')+'</div>').join('')+'</div>').join('')
  ).join('');
}
render(STATE);
const ev = new EventSource('/events?t='+encodeURIComponent(TOKEN));
ev.addEventListener('board', e => render(JSON.parse(e.data)));
</script></body></html>
```

- [ ] **Step 4: Add `render_cockpit` to `coa_serve.py`**

(`os` and `json` are already imported at the top of `coa_serve.py` from Tasks 5–6.) Append:

```python
_COCKPIT_TEMPLATE = os.path.join(os.path.dirname(__file__), "cockpit_template.html")


def render_cockpit(token, state):
    with open(_COCKPIT_TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__COCKPIT_TOKEN__", json.dumps(token))
    html = html.replace("__COCKPIT_JSON__", json.dumps(state))
    return html.encode("utf-8")
```

- [ ] **Step 5: Write the design brief**

Create `docs/design/2026-06-24-coa-cockpit-brief.md` — the cockpit HTML handoff, sibling of the AAR/COA briefs. It must specify: the four-column kanban with a per-repo tab toggle; drag (Proposed→Queued enqueue via `POST /queue`, reorder within Queued via `POST /reorder`); the SSE `board` event driving in-place DOM patching (no full reload); the war-HUD identity (reuse the AAR palette/frame/firetext); the security note (POSTs send the `X-Scorch-Token` header and job-ids only, never commands); and the data contract (`const TOKEN = __COCKPIT_TOKEN__; const STATE = __COCKPIT_JSON__;` with the `state_json` shape `{repos:[{repo,name,proposed[],queued[],finished[]}],running,busy}`). Include a sample STATE. (This is a documentation deliverable; no test.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — `+2` renderer checks.

- [ ] **Step 7: Commit**

```bash
git add src/scorched_earth/cockpit_template.html src/scorched_earth/coa_serve.py docs/design/2026-06-24-coa-cockpit-brief.md tests/test_cockpit.py
git commit -m "feat(cockpit): render_cockpit + self-contained stub template + design brief"
```

---

### Task 8: CLI verb `scorch coa --serve [<repo>]`

**Files:**
- Modify: `bin/scorch` (`_coa_run_cli`)
- Test: `tests/test_cockpit.py`

**Interfaces:**
- Adds `--serve` handling to `_coa_run_cli`: `scorch coa --serve [<repo>]` → resolve repos (the named repo, else all `coa_io.list_repos()`); refuse cleanly if none linked; mint a token (`secrets.token_urlsafe(32)`), build the `Engine` + `make_server(..., render=render_cockpit)`, print the tokened URL, open the browser (`_open_file`-style via the URL), and `serve_forever()` until Ctrl-C.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cockpit.py` (subprocess, temp HOME — exercises only the no-repos refusal so it never blocks on `serve_forever`):

```python
# --- Task 8: CLI verb (no-repos refusal; never starts the blocking server) ---------
import subprocess  # noqa: E402
_cli_env = dict(os.environ); _cli_env["HOME"] = tempfile.mkdtemp()
_scorch = os.path.join(os.path.dirname(__file__), "..", "bin", "scorch")
_p = subprocess.run([sys.executable, _scorch, "coa", "--serve"],
                    capture_output=True, text=True, env=_cli_env, timeout=10)
check("scorch coa --serve with no linked repos refuses cleanly (exit 0, no traceback)",
      _p.returncode == 0 and "Traceback" not in _p.stderr
      and ("link" in _p.stdout.lower() or "no repos" in _p.stdout.lower()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL — `scorch coa --serve` currently falls through (no `--serve` branch); the refusal text isn't printed.

- [ ] **Step 3: Add the `--serve` branch to `bin/scorch`**

In `_coa_run_cli`, at the top of the function (after `sub = rest[0] if rest else "review"`), handle `--serve` as a sub or flag. Since `--serve` may appear as `coa --serve`, detect it in `rest`:

```python
    if "--serve" in rest or sub == "serve":
        import secrets, webbrowser
        from scorched_earth import coa_serve
        named = [a for a in rest if not a.startswith("-") and a != "serve"]
        repos = [named[0]] if named else coa_io.list_repos()
        if not repos:
            print("No repos linked. Use: scorch link <path>")
            return 0
        token = secrets.token_urlsafe(32)
        engine = coa_serve.Engine(repos)
        httpd, port = coa_serve.make_server(engine, token, render=coa_serve.render_cockpit)
        url = f"http://127.0.0.1:{port}/?t={token}"
        print(f"COA cockpit on {url}\n(Ctrl-C to stop)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nCockpit stopped.")
        return 0
```

(Place this branch BEFORE the `queue`/`run`/`review` sub handling so `--serve` is caught first. `webbrowser` is stdlib.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — `+1` CLI check. The subprocess returns immediately because there are no linked repos (it never reaches `serve_forever`).

- [ ] **Step 5: Commit**

```bash
git add bin/scorch tests/test_cockpit.py
git commit -m "feat(cockpit): scorch coa --serve verb (token + browser + serve_forever)"
```

---

### Task 9: Wire CI + docs

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `commands/coa.md`, `CLAUDE.md`, `docs/playbook.md`

- [ ] **Step 1: Add cockpit tests to CI**

In `.github/workflows/tests.yml`, after the "Runner tests" step:

```yaml
      - name: Cockpit tests
        run: python3 tests/test_cockpit.py
```

- [ ] **Step 2: Document `--serve` in `commands/coa.md`**

Append (read the file first to match voice):

```markdown
## Live cockpit (Phase 2b)

`scorch coa --serve [<repo>]` opens a localhost cockpit — a live kanban board (Proposed →
Queued → Running → Secured/Cratered) with a per-repo tab toggle. Drag a job into Queued, reorder
what burns first, hit Run, and watch cards advance in place as work completes. The runner is
event-driven (one job at a time; no background loop). Security: binds 127.0.0.1, a one-time token
is required on every request, the server runs only the agent-supplied launch for a queued job-id
(never a command from the page), ROE is enforced server-side, and it dies when you Ctrl-C. Every
job still runs under the Phase 2a sandbox. Closing the window or Ctrl-C stops it.
```

- [ ] **Step 3: Update `CLAUDE.md` architecture list**

Add after the `review_report.py` line:

```markdown
- `src/scorched_earth/coa_serve.py` + `cockpit_template.html` — COA live cockpit (Phase 2b): a 127.0.0.1 `ThreadingHTTPServer` (one-time token, job-ids-not-commands, ROE server-side) hosting an event-driven `Engine.advance` step (no background loop) that drives the Phase 2a runner; SSE pushes board state to a kanban cockpit. `scorch coa --serve`.
```

- [ ] **Step 4: Update `docs/playbook.md`**

Update the test-count line to add the cockpit checks (use the actual final `tests/test_cockpit.py` count) and note Phase 2b (cockpit) built in Current Status.

- [ ] **Step 5: Run the full suite**

Run: `python3 tests/test_scorched.py && python3 tests/test_advisor.py && python3 tests/test_runner.py && python3 tests/test_cockpit.py`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/tests.yml commands/coa.md CLAUDE.md docs/playbook.md
git commit -m "docs+ci(cockpit): wire test_cockpit into CI; document scorch coa --serve"
```

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-06-24-coa-cockpit-phase2b-design.md`):
- Localhost server, 127.0.0.1, one-time token every request → Task 6 (`make_server`, token checks). ✓
- Job-ids-not-commands → Task 6 (POST ignores `cmd`/`launch`; test asserts a raw command runs nothing). ✓
- ROE server-side → Task 5 (`advance` loads ROE, `pick_next` uses `_allowed_unattended`). ✓
- Unified board: per-repo toggle, four columns → Task 4 (`board_state`), Task 7 (template columns + tabs in the design brief). ✓
- SSE push + in-place patch → Task 6 (`/events`, broadcast), Task 7 (EventSource in stub + brief). ✓
- Queue/unqueue/reorder/run/stop → Task 3 (ops), Task 5 (engine methods), Task 6 (endpoints). ✓
- Event-driven `advance`, four guards → Task 5 (one-at-a-time, remove-on-pick, terminate-by-default, no-retry; tests for each). ✓
- Refreshing envelope, predict-then-re-sync → Task 2 (`EnvelopeTracker`), Task 5 (used in `advance`). ✓
- Reuse Phase 2a `execute_job`; `run_one` extraction → Task 1, Task 5 (`run_one` called, no new exec path). ✓
- Cockpit is a third template; static AAR/COA stay → Task 7 (new template; nothing removed). ✓
- Thread safety → Task 5 (`_lock`, execute outside lock), Task 6 (worker threads for /queue,/run). ✓

**2. Placeholder scan:** No TBD/TODO. The stub `cockpit_template.html` is an explicit working placeholder (renders state, drives SSE) the design brief replaces with no Python change — not a plan placeholder. The Task 7 brief is a documentation deliverable described concretely.

**3. Type/name consistency:** `Engine(repos, *, execute, broadcast, load_state, now)`, `Engine.advance/queue/unqueue/reorder/run/stop/state_json`, `make_server(engine, token, *, render) -> (httpd, port)`, `render_cockpit(token, state) -> bytes`, tokens `__COCKPIT_TOKEN__`/`__COCKPIT_JSON__`, SSE event `board`, snapshot field `state["snapshot"]["now"]` — consistent across Tasks 5/6/7/8. `run_one(repo, job, roe, repo_disp, seq, *, execute, on_running)` consistent between Task 1 (def + run_queue call) and Task 5 (engine call). `EnvelopeTracker.available(state, now)` / `.charge(est)` consistent between Task 2 and Task 5. `pick_next(queue, available, roe)` consistent between Task 2 and Task 5.
